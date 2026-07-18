from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .analytics import calculate_metrics
from .models import BacktestConfig, BacktestResult, Execution, PriceBar, RoundResult, State
from .precision import (
    ONE,
    ZERO,
    decimal,
    floor_int,
    mean_decimal,
    round_market_price,
    round_money,
    round_order_price,
    round_rate,
    round_t,
)


def calculate_star_percent(config: BacktestConfig, t_value: Decimal) -> Decimal:
    """Official 20/40 formulas, generalized for the legacy experimental 30 split."""
    sell_percent = config.effective_sell_percent
    slope = (sell_percent * Decimal("2")) / Decimal(config.split_count)
    return (sell_percent - slope * t_value) / Decimal("100")


def apply_t_effect(t_value: Decimal, effect: str, split_count: int) -> Decimal:
    if effect == "buy_full":
        return round_t(t_value + ONE)
    if effect == "buy_half":
        return round_t(t_value + Decimal("0.5"))
    if effect == "quarter_sell":
        return round_t(t_value * Decimal("0.75"))
    if effect == "limit_sell":
        return round_t(t_value * Decimal("0.25"))
    if effect == "reverse_sell":
        return round_t(t_value * (ONE - Decimal("2") / Decimal(split_count)))
    if effect == "reverse_buy":
        return round_t(t_value + (Decimal(split_count) - t_value) * Decimal("0.25"))
    if effect == "full_sell":
        return ZERO
    return round_t(t_value)


class Simulator:
    def __init__(
        self,
        config: BacktestConfig,
        prices: list[PriceBar],
        data_diagnostics: dict | None = None,
        benchmark_prices: list[PriceBar] | None = None,
    ):
        if not prices:
            raise ValueError("백테스트에는 최소 1거래일이 필요합니다.")
        self.config = config
        self.prices = prices
        self.benchmark_prices = benchmark_prices or []
        self._benchmark_by_date = {item.date: item.close for item in self.benchmark_prices}
        self._benchmark_start = self.benchmark_prices[0].close if self.benchmark_prices else None
        self._benchmark_last = self._benchmark_start
        self.state = State(
            allocation_principal=round_money(config.principal),
            cash_balance=round_money(config.principal),
            round_start_equity=round_money(config.principal),
        )
        self.executions: list[Execution] = []
        self.rounds: list[RoundResult] = []
        self.equity_curve: list[dict] = []
        self.diagnostics = dict(data_diagnostics or {})
        self.diagnostics.update({
            "limit_sell_attempts": 0,
            "limit_sell_fills": 0,
            "intraday_high_only_fills": 0,
            "loc_buy_fills": 0,
            "loc_sell_fills": 0,
            "reverse_entries": 0,
            "reverse_returns": 0,
            "zero_share_orders": 0,
        })
        self.warnings: list[str] = []
        if config.split_count == 30:
            self.warnings.append("30분할은 기존 백테스트 호환용 보간 모델입니다. 공식 문서와 웹앱의 지원 범위는 20/40분할입니다.")
        if config.fill_model == "close_only":
            self.warnings.append("종가 전용 체결 모델입니다. 장중 고가가 최종 매도가를 통과한 체결을 누락할 수 있습니다.")
        if any((config.slippage_bps, config.commission, config.sell_fee_bps)):
            self.warnings.append("수수료/슬리피지는 사용자 입력 가정이며 실제 증권사 체결 비용과 다를 수 있습니다.")

    def _next_fill_price(self, side: str, base_price: Decimal, limit_price: Decimal | None = None) -> Decimal:
        slip = self.config.slippage_bps / Decimal("10000")
        if side == "buy":
            fill = base_price * (ONE + slip)
            if limit_price is not None:
                fill = min(fill, limit_price)
        else:
            fill = base_price * (ONE - slip)
            if limit_price is not None:
                fill = max(fill, limit_price)
        return round_market_price(fill)

    def _record(
        self,
        day: PriceBar,
        side: str,
        order_type: str,
        label: str,
        order_price: Decimal | None,
        fill_price: Decimal,
        quantity: int,
        gross: Decimal,
        fees: Decimal,
        t_before: Decimal,
        t_after: Decimal,
        t_effect: str,
        intraday_triggered: bool = False,
        realized_profit: Decimal = ZERO,
    ) -> None:
        net_cash_flow = round_money(-(gross + fees) if side == "buy" else gross - fees)
        self.executions.append(Execution(
            sequence=len(self.executions) + 1,
            round_number=self.state.round_number,
            date=day.date,
            mode=self.state.mode,
            side=side,
            order_type=order_type,
            label=label,
            order_price=order_price,
            fill_price=fill_price,
            quantity=quantity,
            gross_amount=gross,
            fees=fees,
            net_cash_flow=net_cash_flow,
            t_before=t_before,
            t_after=t_after,
            t_effect=t_effect,
            intraday_triggered=intraday_triggered,
            close_below_order_price=bool(order_price is not None and day.close < order_price),
            realized_profit=realized_profit,
        ))

    def _buy(
        self,
        day: PriceBar,
        label: str,
        order_type: str,
        budget: Decimal,
        t_effect: str,
        limit_price: Decimal | None = None,
    ) -> bool:
        budget = max(round_money(budget), ZERO)
        if budget <= ZERO or self.state.cash_balance <= ZERO:
            return False
        if order_type == "LOC":
            if limit_price is None or day.close > limit_price:
                return False
            fill_price = self._next_fill_price("buy", day.close, limit_price)
            sizing_price = limit_price
        else:
            fill_price = self._next_fill_price("buy", day.close)
            sizing_price = fill_price

        spendable = min(budget, self.state.cash_balance)
        available_for_gross = max(spendable - self.config.commission, ZERO)
        quantity = floor_int(available_for_gross / sizing_price)
        if quantity <= 0:
            self.diagnostics["zero_share_orders"] += 1
            return False
        gross = round_money(fill_price * quantity)
        fees = round_money(self.config.commission)
        while quantity > 0 and gross + fees > self.state.cash_balance:
            quantity -= 1
            gross = round_money(fill_price * quantity)
        if quantity <= 0:
            self.diagnostics["zero_share_orders"] += 1
            return False

        previous_quantity = self.state.position_qty
        previous_cost = self.state.avg_price * previous_quantity
        t_before = self.state.t_value
        self.state.cash_balance = round_money(self.state.cash_balance - gross - fees)
        self.state.position_qty += quantity
        self.state.avg_price = round_money((previous_cost + gross) / Decimal(self.state.position_qty))
        self.state.t_value = apply_t_effect(t_before, t_effect, self.config.split_count)
        self._record(day, "buy", order_type, label, limit_price, fill_price, quantity, gross, fees, t_before, self.state.t_value, t_effect)
        if order_type == "LOC":
            self.diagnostics["loc_buy_fills"] += 1
        return True

    def _sell(
        self,
        day: PriceBar,
        label: str,
        order_type: str,
        planned_quantity: int,
        t_effect: str,
        limit_price: Decimal | None = None,
    ) -> bool:
        quantity = min(planned_quantity, self.state.position_qty)
        if quantity <= 0:
            return False
        intraday_triggered = False
        if order_type == "LIMIT":
            if limit_price is None:
                return False
            self.diagnostics["limit_sell_attempts"] += 1
            trigger_price = day.high if self.config.fill_model == "intraday_high" else day.close
            if trigger_price < limit_price:
                return False
            fill_price = limit_price
            intraday_triggered = self.config.fill_model == "intraday_high" and day.close < limit_price
        elif order_type == "LOC":
            if limit_price is None or day.close < limit_price:
                return False
            fill_price = self._next_fill_price("sell", day.close, limit_price)
        else:
            fill_price = self._next_fill_price("sell", day.close)

        gross = round_money(fill_price * quantity)
        fees = round_money(self.config.commission + gross * self.config.sell_fee_bps / Decimal("10000"))
        realized = round_money((fill_price - self.state.avg_price) * quantity - fees)
        t_before = self.state.t_value
        self.state.cash_balance = round_money(self.state.cash_balance + gross - fees)
        self.state.position_qty -= quantity
        self.state.t_value = apply_t_effect(t_before, t_effect, self.config.split_count)
        self.state.realized_profit = round_money(self.state.realized_profit + realized)
        self._record(
            day, "sell", order_type, label, limit_price, fill_price, quantity, gross, fees,
            t_before, self.state.t_value, t_effect, intraday_triggered, realized,
        )
        if order_type == "LIMIT":
            self.diagnostics["limit_sell_fills"] += 1
            if intraday_triggered:
                self.diagnostics["intraday_high_only_fills"] += 1
        elif order_type == "LOC":
            self.diagnostics["loc_sell_fills"] += 1
        if self.state.position_qty == 0:
            self.state.avg_price = ZERO
        return True

    def _start_round(self, day: PriceBar, previous_close: Decimal | None, force_moc: bool = False) -> bool:
        if self.state.position_qty != 0 or self.state.t_value != ZERO:
            return False
        one_unit_budget = round_money(self.state.allocation_principal / Decimal(self.config.split_count))
        starting_equity = self.state.cash_balance
        if force_moc or self.config.initial_entry == "moc" or previous_close is None:
            filled = self._buy(day, "첫 매수", "MOC", one_unit_budget, "buy_full")
        else:
            buffer = ONE + self.config.first_buy_buffer_percent / Decimal("100")
            limit_price = round_order_price(previous_close * buffer)
            filled = self._buy(day, "첫 매수", "LOC", one_unit_budget, "buy_full", limit_price)
        if filled:
            self.state.round_started_at = day.date
            self.state.round_start_equity = starting_equity
            self.state.round_trading_days = 1
        return filled

    def _complete_round(self, day: PriceBar) -> None:
        round_executions = [item for item in self.executions if item.round_number == self.state.round_number]
        starting = self.state.round_start_equity
        ending = self.state.cash_balance
        profit = round_money(ending - starting)
        profit_rate = round_rate((profit / starting) * Decimal("100")) if starting > ZERO else ZERO
        started_at = self.state.round_started_at or day.date
        calendar_days = (datetime.strptime(day.date, "%Y-%m-%d") - datetime.strptime(started_at, "%Y-%m-%d")).days + 1
        self.rounds.append(RoundResult(
            round_number=self.state.round_number,
            started_at=started_at,
            ended_at=day.date,
            allocation_principal=self.state.allocation_principal,
            starting_equity=starting,
            ending_equity=ending,
            profit_amount=profit,
            profit_rate=profit_rate,
            calendar_days=calendar_days,
            trading_days=self.state.round_trading_days,
            execution_count=len(round_executions),
            buy_count=sum(1 for item in round_executions if item.side == "buy"),
            sell_count=sum(1 for item in round_executions if item.side == "sell"),
            total_buy_amount=round_money(sum((item.gross_amount for item in round_executions if item.side == "buy"), ZERO)),
            total_sell_amount=round_money(sum((item.gross_amount for item in round_executions if item.side == "sell"), ZERO)),
            total_fees=round_money(sum((item.fees for item in round_executions), ZERO)),
            ending_t_value=self.state.t_value,
        ))
        if self.config.compounding_type == "compound":
            self.state.allocation_principal = ending
        self.state.position_qty = 0
        self.state.avg_price = ZERO
        self.state.t_value = ZERO
        self.state.mode = "normal"
        self.state.reverse_first_sell_done = False
        self.state.round_number += 1
        self.state.round_started_at = None
        self.state.round_start_equity = ending
        self.state.round_trading_days = 0

    def _process_normal_day(self, day: PriceBar) -> None:
        if self.state.t_value > Decimal(self.config.split_count - 1):
            self.state.mode = "reverse"
            self.state.reverse_first_sell_done = False
            self.diagnostics["reverse_entries"] += 1
            return

        starting_t = self.state.t_value
        starting_qty = self.state.position_qty
        starting_avg = self.state.avg_price
        starting_cash = self.state.cash_balance
        star_percent = calculate_star_percent(self.config, starting_t)
        star_price = round_order_price(starting_avg * (ONE + star_percent))
        buy_price = round_order_price(star_price - Decimal("0.01"))
        target_sell_price = round_order_price(starting_avg * (ONE + self.config.effective_sell_percent / Decimal("100")))
        remaining_turns = Decimal(self.config.split_count) - starting_t
        one_unit_budget = round_money(starting_cash / remaining_turns) if remaining_turns > ZERO else ZERO
        quarter_qty = floor_int(Decimal(starting_qty) / Decimal("4"))
        final_qty = max(starting_qty - quarter_qty, 0)

        # The limit order is active intraday; LOC decisions settle at the close.
        self._sell(day, "최종 지정가 매도", "LIMIT", final_qty, "limit_sell", target_sell_price)
        self._sell(day, "쿼터매도", "LOC", quarter_qty, "quarter_sell", star_price)
        if self.state.position_qty == 0:
            self._complete_round(day)
            return

        if starting_t < Decimal(self.config.split_count) / Decimal("2"):
            half_budget = round_money(one_unit_budget / Decimal("2"))
            self._buy(day, "전반전 별지점 매수", "LOC", half_budget, "buy_half", buy_price)
            self._buy(day, "전반전 평단 매수", "LOC", half_budget, "buy_half", round_order_price(starting_avg))
        else:
            self._buy(day, "후반전 별지점 매수", "LOC", one_unit_budget, "buy_full", buy_price)

    def _process_reverse_day(self, day: PriceBar, previous_closes: list[Decimal]) -> None:
        divisor = Decimal(self.config.split_count) / Decimal("2")
        sell_quantity = floor_int(Decimal(self.state.position_qty) / divisor)
        if not self.state.reverse_first_sell_done:
            self._sell(day, "리버스 첫날 매도", "MOC", sell_quantity, "reverse_sell")
            self.state.reverse_first_sell_done = True
            self._return_from_reverse_if_ready(day)
            return

        reference = mean_decimal(previous_closes[-5:]) if len(previous_closes) >= 5 else None
        if reference is None:
            self.warnings.append(f"{day.date}: 리버스 기준가 계산에 필요한 직전 5거래일 종가가 없습니다.")
            return
        if day.close > reference:
            self._sell(day, "리버스 매도", "MOC", sell_quantity, "reverse_sell")
        elif day.close < reference:
            self._buy(day, "리버스 쿼터매수", "MOC", round_money(self.state.cash_balance / Decimal("4")), "reverse_buy")

        self._return_from_reverse_if_ready(day)

    def _return_from_reverse_if_ready(self, day: PriceBar) -> None:
        if self.state.position_qty <= 0:
            return
        return_line = self.state.avg_price * (Decimal("0.85") if self.config.symbol == "TQQQ" else Decimal("0.80"))
        if day.close > return_line:
            self.state.mode = "normal"
            self.state.reverse_first_sell_done = False
            self.diagnostics["reverse_returns"] += 1

    def _append_equity(self, day: PriceBar) -> None:
        equity = round_money(self.state.cash_balance + self.state.position_qty * day.close)
        start_close = self.prices[0].close
        benchmark_equity = round_money(self.config.principal * day.close / start_close)
        point = {
            "date": day.date,
            "open": day.open,
            "close": day.close,
            "high": day.high,
            "low": day.low,
            "volume": day.volume,
            "equity": equity,
            "benchmark_equity": benchmark_equity,
            "cash_balance": self.state.cash_balance,
            "position_qty": self.state.position_qty,
            "avg_price": self.state.avg_price,
            "t_value": self.state.t_value,
            "mode": self.state.mode,
        }
        if self._benchmark_start:
            self._benchmark_last = self._benchmark_by_date.get(day.date, self._benchmark_last)
            point["qld_benchmark_equity"] = round_money(self.config.principal * self._benchmark_last / self._benchmark_start)
        self.equity_curve.append(point)

    def run(self, stop_after_completed_rounds: int | None = None) -> BacktestResult:
        if stop_after_completed_rounds is not None and stop_after_completed_rounds <= 0:
            raise ValueError("종료할 라운드 수는 1 이상이어야 합니다.")
        first_day = self.prices[0]
        if not self._start_round(first_day, None, force_moc=True):
            raise ValueError("원금이 너무 작아 첫 거래일에 1주도 매수할 수 없습니다.")
        self._append_equity(first_day)

        for index, day in enumerate(self.prices[1:], start=1):
            opened = False
            if self.state.position_qty == 0 and self.state.t_value == ZERO:
                opened = self._start_round(day, self.prices[index - 1].close)
            if not opened and self.state.position_qty > 0:
                self.state.round_trading_days += 1
                if self.state.mode == "normal":
                    self._process_normal_day(day)
                else:
                    previous_closes = [item.close for item in self.prices[max(0, index - 5):index]]
                    self._process_reverse_day(day, previous_closes)
            self._append_equity(day)
            if stop_after_completed_rounds is not None and len(self.rounds) >= stop_after_completed_rounds:
                break

        metrics, monthly_returns, yearly_returns = calculate_metrics(
            self.equity_curve,
            self.executions,
            self.rounds,
            self.config.principal,
            self.config.annual_risk_free_rate,
        )
        ending_equity = decimal(self.equity_curve[-1]["equity"])
        benchmark_ending = decimal(self.equity_curve[-1]["benchmark_equity"])
        profit = round_money(ending_equity - self.config.principal)
        profit_rate = round_rate((profit / self.config.principal) * Decimal("100"))
        benchmark_rate = round_rate(((benchmark_ending / self.config.principal) - ONE) * Decimal("100"))
        qld_ending = decimal(self.equity_curve[-1].get("qld_benchmark_equity")) if self._benchmark_start else None
        qld_rate = round_rate(((qld_ending / self.config.principal) - ONE) * Decimal("100")) if qld_ending is not None else None
        first_date = datetime.strptime(self.prices[0].date, "%Y-%m-%d")
        last_date = datetime.strptime(self.equity_curve[-1]["date"], "%Y-%m-%d")

        if self.diagnostics["intraday_high_only_fills"]:
            count = self.diagnostics["intraday_high_only_fills"]
            self.warnings.append(f"종가 미도달이지만 장중 고가로 체결된 최종 지정가 매도가 {count}건 있습니다.")
        self.diagnostics["calculation_precision"] = {
            "order_price_decimals": 2,
            "cash_and_average_decimals": 4,
            "market_price_decimals": 6,
            "t_value_decimals": 10,
            "rounding": "ROUND_HALF_UP",
        }
        self.diagnostics["loc_rule"] = "매수: close <= limit, 매도: close >= limit, 체결 기준가는 close"
        self.diagnostics["limit_rule"] = "intraday_high: high >= target, close_only: close >= target"

        return BacktestResult(
            config={
                "symbol": self.config.symbol,
                "split_count": self.config.split_count,
                "principal": self.config.principal,
                "compounding_type": self.config.compounding_type,
                "sell_percent": self.config.effective_sell_percent,
                "fill_model": self.config.fill_model,
                "initial_entry": self.config.initial_entry,
                "first_buy_buffer_percent": self.config.first_buy_buffer_percent,
                "slippage_bps": self.config.slippage_bps,
                "commission": self.config.commission,
                "sell_fee_bps": self.config.sell_fee_bps,
                "annual_risk_free_rate": self.config.annual_risk_free_rate,
            },
            period={
                "start": self.prices[0].date,
                "end": self.equity_curve[-1]["date"],
                "trading_days": len(self.equity_curve),
                "calendar_days": (last_date - first_date).days + 1,
            },
            summary={
                "ending_equity": ending_equity,
                "profit_amount": profit,
                "profit_rate": profit_rate,
                "benchmark_ending_equity": benchmark_ending,
                "benchmark_profit_rate": benchmark_rate,
                "qld_benchmark_ending_equity": qld_ending,
                "qld_benchmark_profit_rate": qld_rate,
                "excess_return_rate": round_rate(profit_rate - benchmark_rate),
                "completed_rounds": len(self.rounds),
                "execution_count": len(self.executions),
                "open_position_qty": self.state.position_qty,
                "cash_balance": self.state.cash_balance,
                "open_position_market_value": round_money(self.state.position_qty * decimal(self.equity_curve[-1]["close"])),
            },
            metrics=metrics,
            state={
                "allocation_principal": self.state.allocation_principal,
                "cash_balance": self.state.cash_balance,
                "position_qty": self.state.position_qty,
                "avg_price": self.state.avg_price,
                "t_value": self.state.t_value,
                "mode": self.state.mode,
                "round_number": self.state.round_number,
                "round_started_at": self.state.round_started_at,
            },
            rounds=self.rounds,
            executions=self.executions,
            equity_curve=self.equity_curve,
            monthly_returns=monthly_returns,
            yearly_returns=yearly_returns,
            diagnostics=self.diagnostics,
            warnings=list(dict.fromkeys(self.warnings)),
        )


def run_backtest(
    config: BacktestConfig,
    prices: list[PriceBar],
    data_diagnostics: dict | None = None,
    benchmark_prices: list[PriceBar] | None = None,
    stop_after_completed_rounds: int | None = None,
) -> BacktestResult:
    return Simulator(config, prices, data_diagnostics, benchmark_prices).run(stop_after_completed_rounds)
