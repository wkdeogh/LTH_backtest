from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, localcontext

from .data import align_price_series
from .models import PriceBar
from .performance import calculate_equity_performance
from .precision import ONE, ZERO, decimal, round_market_price, round_money, round_rate


SHARE_QUANTUM = Decimal("0.00000001")


@dataclass
class PreviousHighConfig:
    principal: Decimal
    trigger_interval_pct: Decimal = Decimal("5")
    divisions: int = 20
    fractional_shares: bool = False
    liquidation_offset_pct: Decimal = ZERO
    slippage_bps: Decimal = ZERO
    commission: Decimal = ZERO
    sell_fee_bps: Decimal = ZERO
    annual_risk_free_rate: Decimal = ZERO

    def __post_init__(self) -> None:
        self.principal = decimal(self.principal)
        self.trigger_interval_pct = decimal(self.trigger_interval_pct)
        self.liquidation_offset_pct = decimal(self.liquidation_offset_pct)
        self.slippage_bps = decimal(self.slippage_bps)
        self.commission = decimal(self.commission)
        self.sell_fee_bps = decimal(self.sell_fee_bps)
        self.annual_risk_free_rate = decimal(self.annual_risk_free_rate)
        self.validate()

    def validate(self) -> None:
        numeric_values = {
            "원금": self.principal,
            "매매 간격": self.trigger_interval_pct,
            "전고점 청산 오프셋": self.liquidation_offset_pct,
            "슬리피지": self.slippage_bps,
            "고정 수수료": self.commission,
            "매도 비용": self.sell_fee_bps,
            "무위험 수익률": self.annual_risk_free_rate,
        }
        for label, value in numeric_values.items():
            if not value.is_finite():
                raise ValueError(f"{label}은 유한한 숫자여야 합니다.")
        if self.principal <= ZERO:
            raise ValueError("원금은 0보다 커야 합니다.")
        if self.trigger_interval_pct <= ZERO or self.trigger_interval_pct >= Decimal("100"):
            raise ValueError("매매 간격은 0보다 크고 100보다 작아야 합니다.")
        if self.divisions < 2 or self.divisions > 500:
            raise ValueError("분할 수는 2 이상 500 이하여야 합니다.")
        if not Decimal("-50") <= self.liquidation_offset_pct <= Decimal("50"):
            raise ValueError("전고점 청산 오프셋은 -50% 이상 50% 이하여야 합니다.")
        if self.slippage_bps < ZERO or self.slippage_bps >= Decimal("10000"):
            raise ValueError("슬리피지는 0bp 이상 10,000bp 미만이어야 합니다.")
        if self.commission < ZERO:
            raise ValueError("고정 수수료는 음수일 수 없습니다.")
        if self.sell_fee_bps < ZERO or self.sell_fee_bps >= Decimal("10000"):
            raise ValueError("매도 비용은 0bp 이상 10,000bp 미만이어야 합니다.")


@dataclass
class PreviousHighTrade:
    sequence: int
    date: str
    round_id: int
    action: str
    trigger_level: Decimal | None
    trigger_steps: list[int]
    execution_type: str
    signal_soxx_price: Decimal
    soxx_price: Decimal
    soxx_shares_before: Decimal
    soxx_shares_after: Decimal
    soxl_price: Decimal
    soxl_shares_before: Decimal
    soxl_shares_after: Decimal
    cash: Decimal
    total_portfolio_value: Decimal
    soxx_gross: Decimal
    soxl_gross: Decimal
    fees: Decimal
    funded_equivalent_steps: Decimal
    order_count: int


@dataclass
class PreviousHighRound:
    round_id: int
    start_date: str
    first_conversion_date: str
    end_date: str
    end_phase: str
    peak_recorded_at: str
    start_peak: Decimal
    basis_amount: Decimal
    start_portfolio_value: Decimal
    end_portfolio_value: Decimal
    return_pct: Decimal
    duration_days: int
    duration_trading_days: int
    recovery_trading_days: int
    max_soxx_drawdown: Decimal = ZERO
    max_portfolio_drawdown: Decimal = ZERO
    max_loss_from_start: Decimal = ZERO
    max_soxl_weight: Decimal = ZERO
    max_effective_leverage: Decimal = ZERO
    number_of_conversion_steps: int = 0
    conversion_events: int = 0
    total_fees: Decimal = ZERO
    soxx_exhausted: bool = False
    exhaustion_drawdown: Decimal | None = None
    mdd_peak_date: str | None = None
    mdd_trough_date: str | None = None


@dataclass
class PreviousHighState:
    cash: Decimal
    soxx_shares: Decimal = ZERO
    soxl_shares: Decimal = ZERO
    peak_price: Decimal = ZERO
    peak_date: str | None = None
    peak_portfolio_value: Decimal = ZERO
    basis_amount: Decimal = ZERO
    round_id: int = 1
    round_anchor_date: str | None = None
    round_anchor_equity: Decimal = ZERO
    first_conversion_date: str | None = None
    executed_levels: set[int] = field(default_factory=set)
    round_conversion_steps: int = 0
    round_conversion_events: int = 0
    round_fees: Decimal = ZERO
    round_exhausted: bool = False
    round_exhaustion_drawdown: Decimal | None = None


def _share_quantity(value: Decimal, fractional: bool) -> Decimal:
    if not value.is_finite() or value <= ZERO:
        return ZERO
    if fractional:
        return value.quantize(SHARE_QUANTUM, rounding=ROUND_DOWN)
    return Decimal(int(value // ONE))


def _affordable_quantity(budget: Decimal, fill_price: Decimal, fee: Decimal, fractional: bool) -> Decimal:
    """Return a floored quantity whose rounded gross plus fee never exceeds budget."""
    quantity = _share_quantity(max(budget - fee, ZERO) / fill_price, fractional)
    decrement = SHARE_QUANTUM if fractional else ONE
    while quantity > ZERO and round_money(quantity * fill_price) + fee > budget:
        quantity = max(quantity - decrement, ZERO)
    return quantity


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _resolved_price_basis(data_diagnostics: dict | None) -> str:
    """Resolve a shared SOXX/SOXL basis without claiming unknown CSVs are actual."""
    diagnostics = data_diagnostics or {}
    candidates: list[str] = []
    direct = diagnostics.get("price_basis")
    if direct:
        candidates.append(str(direct))
    for symbol in ("SOXX", "SOXL"):
        nested = diagnostics.get(symbol)
        if isinstance(nested, dict) and nested.get("price_basis"):
            candidates.append(str(nested["price_basis"]))
    unique = set(candidates)
    if len(unique) == 1:
        return candidates[0]
    if len(unique) > 1:
        return "mixed"
    return "unknown"


class PreviousHighSimulator:
    def __init__(
        self,
        config: PreviousHighConfig,
        soxx_prices: list[PriceBar],
        soxl_prices: list[PriceBar],
        data_diagnostics: dict | None = None,
    ) -> None:
        self.config = config
        self.pairs, alignment = align_price_series(soxx_prices, soxl_prices, "SOXX", "SOXL")
        self.price_basis = _resolved_price_basis(data_diagnostics)
        self.state = PreviousHighState(cash=round_money(config.principal))
        self.trades: list[PreviousHighTrade] = []
        self.rounds: list[PreviousHighRound] = []
        self.equity_curve: list[dict] = []
        self.round_path_points: list[dict] = []
        self.round_anchor_path_sequences: dict[int, int] = {}
        self.diagnostics = dict(data_diagnostics or {})
        self.diagnostics["alignment"] = alignment
        self.diagnostics.update({
            "conversion_events": 0,
            "recovery_events": 0,
            "executed_steps": 0,
            "max_reached_stage": 0,
            "zero_share_attempts": 0,
            "order_count": 0,
            "soxx_exhaustion_events": 0,
            "price_trigger_fields": "SOXX open/close only; high/low ignored",
            "phase_order": "OPEN recovery -> OPEN conversion -> CLOSE recovery -> CLOSE conversion -> close peak update",
            "risk_metric_sampling": "round/max exposure: post-trade open/close plus daily close; strategy MDD: daily close only",
            "resolved_price_basis": self.price_basis,
        })
        self.warnings = [
            "SOXX와 SOXL의 공통 거래일만 사용하며 누락일을 전일 가격으로 채우지 않습니다.",
            "장중 High/Low만 조건을 통과한 경우 체결하지 않습니다.",
        ]
        if self.price_basis == "actual_split_adjusted":
            self.warnings.append("분할 반영·배당 미보정 실제 OHLC 가격수익률 기준입니다. 현금 분배금은 별도로 가산하지 않습니다.")
        else:
            self.warnings.append(
                f"가격 기준은 {self.price_basis}입니다. 사용자 CSV의 분할·배당 조정 여부를 엔진이 확인할 수 없으므로 실제 거래가격으로 단정하지 않습니다."
            )
        if config.fractional_shares:
            self.warnings.append("소수점 수량은 소수 8자리에서 버림 처리하는 이론적 체결입니다.")
        if config.liquidation_offset_pct != ZERO:
            self.warnings.append("전고점 청산 오프셋은 원본 규칙과 분리된 실험 옵션입니다.")
        if any((config.slippage_bps, config.commission, config.sell_fee_bps)):
            self.warnings.append("거래비용은 사용자 입력 가정이며 실제 증권사 비용과 다를 수 있습니다.")

    def _fill_price(self, side: str, base_price: Decimal) -> Decimal:
        slippage = self.config.slippage_bps / Decimal("10000")
        multiplier = ONE + slippage if side == "buy" else ONE - slippage
        return round_market_price(base_price * multiplier)

    def _sell_fees(self, gross: Decimal) -> Decimal:
        return round_money(self.config.commission + gross * self.config.sell_fee_bps / Decimal("10000"))

    def _portfolio_value(self, soxx_price: Decimal, soxl_price: Decimal) -> Decimal:
        return round_money(
            self.state.cash
            + self.state.soxx_shares * soxx_price
            + self.state.soxl_shares * soxl_price
        )

    def _record_round_path_point(
        self,
        *,
        date_value: str,
        phase: str,
        soxx_price: Decimal,
        soxl_price: Decimal,
    ) -> None:
        """Capture post-action exposure at the market signal price for round risk metrics."""
        equity = self._portfolio_value(soxx_price, soxl_price)
        soxl_value = round_money(self.state.soxl_shares * soxl_price)
        soxx_value = round_money(self.state.soxx_shares * soxx_price)
        soxl_weight = soxl_value / equity * Decimal("100") if equity > ZERO else ZERO
        soxx_weight = soxx_value / equity * Decimal("100") if equity > ZERO else ZERO
        effective_leverage = (soxx_weight + soxl_weight * Decimal("3")) / Decimal("100")
        soxx_drawdown = (
            ((soxx_price / self.state.peak_price) - ONE) * Decimal("100")
            if self.state.peak_price > ZERO
            else ZERO
        )
        self.round_path_points.append({
            "sequence": len(self.round_path_points) + 1,
            "round_id": self.state.round_id,
            "date": date_value,
            "phase": phase,
            "equity": equity,
            "soxx_drawdown": round_rate(soxx_drawdown),
            "soxl_weight": round_rate(soxl_weight),
            "effective_leverage": round_rate(effective_leverage),
        })

    def _record_trade(
        self,
        *,
        date_value: str,
        action: str,
        trigger_level: Decimal | None,
        trigger_steps: list[int],
        phase: str,
        signal_soxx_price: Decimal,
        signal_soxl_price: Decimal,
        soxx_fill: Decimal,
        soxx_before: Decimal,
        soxl_fill: Decimal,
        soxl_before: Decimal,
        soxx_gross: Decimal,
        soxl_gross: Decimal,
        fees: Decimal,
        funded_equivalent_steps: Decimal = ZERO,
        order_count: int = 2,
    ) -> None:
        self.trades.append(PreviousHighTrade(
            sequence=len(self.trades) + 1,
            date=date_value,
            round_id=self.state.round_id,
            action=action,
            trigger_level=trigger_level,
            trigger_steps=trigger_steps,
            execution_type=phase,
            signal_soxx_price=signal_soxx_price,
            soxx_price=soxx_fill,
            soxx_shares_before=soxx_before,
            soxx_shares_after=self.state.soxx_shares,
            soxl_price=soxl_fill,
            soxl_shares_before=soxl_before,
            soxl_shares_after=self.state.soxl_shares,
            cash=self.state.cash,
            total_portfolio_value=self._portfolio_value(signal_soxx_price, signal_soxl_price),
            soxx_gross=soxx_gross,
            soxl_gross=soxl_gross,
            fees=fees,
            funded_equivalent_steps=round_rate(funded_equivalent_steps),
            order_count=order_count,
        ))
        self._record_round_path_point(
            date_value=date_value,
            phase=phase,
            soxx_price=signal_soxx_price,
            soxl_price=signal_soxl_price,
        )
        self.diagnostics["order_count"] += order_count

    def _initial_entry(self, soxx: PriceBar, soxl: PriceBar) -> None:
        fill = self._fill_price("buy", soxx.close)
        quantity = _affordable_quantity(
            self.state.cash, fill, self.config.commission, self.config.fractional_shares,
        )
        if quantity <= ZERO:
            raise ValueError("원금이 너무 작아 시작일에 SOXX를 매수할 수 없습니다.")
        gross = round_money(quantity * fill)
        fee = round_money(self.config.commission)
        self.state.cash = round_money(self.state.cash - gross - fee)
        self.state.soxx_shares = quantity
        equity = self._portfolio_value(soxx.close, soxl.close)
        self.state.peak_price = soxx.close
        self.state.peak_date = soxx.date
        self.state.peak_portfolio_value = equity
        self.state.basis_amount = round_money(equity / Decimal(self.config.divisions))
        self.state.round_anchor_date = soxx.date
        self.state.round_anchor_equity = equity
        self._record_trade(
            date_value=soxx.date,
            action="INITIAL_BUY_SOXX",
            trigger_level=None,
            trigger_steps=[],
            phase="close",
            signal_soxx_price=soxx.close,
            signal_soxl_price=soxl.close,
            soxx_fill=fill,
            soxx_before=ZERO,
            soxl_fill=soxl.close,
            soxl_before=ZERO,
            soxx_gross=gross,
            soxl_gross=ZERO,
            fees=fee,
            order_count=1,
        )
        self.round_anchor_path_sequences[self.state.round_id] = len(self.round_path_points)

    def _eligible_stage(self, soxx_price: Decimal) -> int:
        if self.state.peak_price <= ZERO or soxx_price >= self.state.peak_price:
            return 0
        drawdown_fraction = (self.state.peak_price - soxx_price) / self.state.peak_price
        interval_fraction = self.config.trigger_interval_pct / Decimal("100")
        return max(int(drawdown_fraction / interval_fraction), 0)

    def _convert_to_soxl(self, soxx: PriceBar, soxl: PriceBar, phase: str) -> bool:
        signal_soxx = soxx.open if phase == "open" else soxx.close
        signal_soxl = soxl.open if phase == "open" else soxl.close
        reached = self._eligible_stage(signal_soxx)
        self.diagnostics["max_reached_stage"] = max(self.diagnostics["max_reached_stage"], reached)
        new_levels = [level for level in range(1, reached + 1) if level not in self.state.executed_levels]
        if not new_levels or self.state.soxx_shares <= ZERO:
            return False

        soxx_fill = self._fill_price("sell", signal_soxx)
        soxl_fill = self._fill_price("buy", signal_soxl)
        target = round_money(self.state.basis_amount * Decimal(len(new_levels)))
        planned_sale = _share_quantity(target / soxx_fill, self.config.fractional_shares)
        sale_quantity = min(planned_sale, self.state.soxx_shares)
        if self.state.soxx_shares * soxx_fill <= target:
            sale_quantity = self.state.soxx_shares
        if sale_quantity <= ZERO:
            self.diagnostics["zero_share_attempts"] += 1
            return False

        sale_gross = round_money(sale_quantity * soxx_fill)
        funded_step_count = min(
            len(new_levels),
            max(
                1,
                int((sale_gross / self.state.basis_amount).to_integral_value(rounding=ROUND_CEILING))
                if self.state.basis_amount > ZERO
                else 1,
            ),
        )
        executed_levels = new_levels[:funded_step_count]
        sale_fees = self._sell_fees(sale_gross)
        sale_net = round_money(sale_gross - sale_fees)
        buy_quantity = _affordable_quantity(
            sale_net, soxl_fill, self.config.commission, self.config.fractional_shares,
        )
        if buy_quantity <= ZERO:
            self.diagnostics["zero_share_attempts"] += 1
            return False
        buy_gross = round_money(buy_quantity * soxl_fill)
        buy_fee = round_money(self.config.commission)

        soxx_before = self.state.soxx_shares
        soxl_before = self.state.soxl_shares
        self.state.soxx_shares -= sale_quantity
        self.state.soxl_shares += buy_quantity
        self.state.cash = round_money(self.state.cash + sale_gross - sale_fees - buy_gross - buy_fee)
        if self.state.cash < ZERO and abs(self.state.cash) <= Decimal("0.0001"):
            self.state.cash = ZERO
        if self.state.cash < ZERO:
            raise ArithmeticError("전환 후 현금이 음수가 되었습니다.")

        if self.state.first_conversion_date is None:
            self.state.first_conversion_date = soxx.date
        self.state.executed_levels.update(executed_levels)
        self.state.round_conversion_steps += len(executed_levels)
        self.state.round_conversion_events += 1
        fees = round_money(sale_fees + buy_fee)
        self.state.round_fees = round_money(self.state.round_fees + fees)
        self.diagnostics["conversion_events"] += 1
        self.diagnostics["executed_steps"] += len(executed_levels)

        exhausted = self.state.soxx_shares <= ZERO
        if exhausted and not self.state.round_exhausted:
            self.state.round_exhausted = True
            self.state.round_exhaustion_drawdown = round_rate(
                ((signal_soxx / self.state.peak_price) - ONE) * Decimal("100")
            )
            self.diagnostics["soxx_exhaustion_events"] += 1

        deepest_level = max(executed_levels)
        trigger_level = round_market_price(
            self.state.peak_price
            * (ONE - self.config.trigger_interval_pct * Decimal(deepest_level) / Decimal("100"))
        )
        funded = sale_gross / self.state.basis_amount if self.state.basis_amount > ZERO else ZERO
        self._record_trade(
            date_value=soxx.date,
            action="SOXX_TO_SOXL",
            trigger_level=trigger_level,
            trigger_steps=executed_levels,
            phase=phase,
            signal_soxx_price=signal_soxx,
            signal_soxl_price=signal_soxl,
            soxx_fill=soxx_fill,
            soxx_before=soxx_before,
            soxl_fill=soxl_fill,
            soxl_before=soxl_before,
            soxx_gross=sale_gross,
            soxl_gross=buy_gross,
            fees=fees,
            funded_equivalent_steps=funded,
        )
        return True

    def _recover_to_soxx(self, soxx: PriceBar, soxl: PriceBar, phase: str) -> bool:
        if self.state.soxl_shares <= ZERO:
            return False
        signal_soxx = soxx.open if phase == "open" else soxx.close
        signal_soxl = soxl.open if phase == "open" else soxl.close
        recovery_price = self.state.peak_price * (
            ONE + self.config.liquidation_offset_pct / Decimal("100")
        )
        if signal_soxx < recovery_price:
            return False

        soxl_fill = self._fill_price("sell", signal_soxl)
        soxx_fill = self._fill_price("buy", signal_soxx)
        soxx_before = self.state.soxx_shares
        soxl_before = self.state.soxl_shares
        sale_gross = round_money(soxl_before * soxl_fill)
        sale_fees = self._sell_fees(sale_gross)
        sale_net = round_money(sale_gross - sale_fees)
        if sale_net < ZERO:
            raise ValueError("SOXL 회복 매도의 순수입보다 거래비용이 커서 라운드를 종료할 수 없습니다.")
        existing_cash = self.state.cash
        buy_quantity = _affordable_quantity(
            sale_net, soxx_fill, self.config.commission, self.config.fractional_shares,
        )
        buy_gross = round_money(buy_quantity * soxx_fill)
        buy_fee = round_money(self.config.commission) if buy_quantity > ZERO else ZERO

        self.state.soxl_shares = ZERO
        self.state.soxx_shares += buy_quantity
        self.state.cash = round_money(existing_cash + sale_net - buy_gross - buy_fee)
        fees = round_money(sale_fees + buy_fee)
        self.state.round_fees = round_money(self.state.round_fees + fees)
        ending_equity = self._portfolio_value(signal_soxx, signal_soxl)
        start_equity = self.state.round_anchor_equity
        profit_rate = (
            round_rate(((ending_equity / start_equity) - ONE) * Decimal("100"))
            if start_equity > ZERO
            else ZERO
        )
        start_date = self.state.round_anchor_date or self.state.peak_date or soxx.date
        trading_days = sum(1 for left, _ in self.pairs if start_date <= left.date <= soxx.date)
        self.rounds.append(PreviousHighRound(
            round_id=self.state.round_id,
            start_date=start_date,
            first_conversion_date=self.state.first_conversion_date or soxx.date,
            end_date=soxx.date,
            end_phase=phase,
            peak_recorded_at=self.state.peak_date or start_date,
            start_peak=self.state.peak_price,
            basis_amount=self.state.basis_amount,
            start_portfolio_value=start_equity,
            end_portfolio_value=ending_equity,
            return_pct=profit_rate,
            duration_days=(datetime.strptime(soxx.date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days,
            duration_trading_days=trading_days,
            recovery_trading_days=max(trading_days - 1, 0),
            number_of_conversion_steps=self.state.round_conversion_steps,
            conversion_events=self.state.round_conversion_events,
            total_fees=self.state.round_fees,
            soxx_exhausted=self.state.round_exhausted,
            exhaustion_drawdown=self.state.round_exhaustion_drawdown,
        ))
        self._record_trade(
            date_value=soxx.date,
            action="SOXL_TO_SOXX_RECOVERY",
            trigger_level=round_market_price(recovery_price),
            trigger_steps=[],
            phase=phase,
            signal_soxx_price=signal_soxx,
            signal_soxl_price=signal_soxl,
            soxx_fill=soxx_fill,
            soxx_before=soxx_before,
            soxl_fill=soxl_fill,
            soxl_before=soxl_before,
            soxx_gross=buy_gross,
            soxl_gross=sale_gross,
            fees=fees,
            order_count=2 if buy_quantity > ZERO else 1,
        )
        self.diagnostics["recovery_events"] += 1

        self.state.round_id += 1
        self.state.round_anchor_date = soxx.date
        self.state.round_anchor_equity = ending_equity
        self.round_anchor_path_sequences[self.state.round_id] = len(self.round_path_points) + 1
        self.state.first_conversion_date = None
        self.state.executed_levels.clear()
        self.state.round_conversion_steps = 0
        self.state.round_conversion_events = 0
        self.state.round_fees = ZERO
        self.state.round_exhausted = False
        self.state.round_exhaustion_drawdown = None
        return True

    def _update_peak(self, soxx: PriceBar, soxl: PriceBar) -> None:
        if self.state.soxl_shares > ZERO or soxx.close <= self.state.peak_price:
            return
        equity = self._portfolio_value(soxx.close, soxl.close)
        self.state.peak_price = soxx.close
        self.state.peak_date = soxx.date
        self.state.peak_portfolio_value = equity
        self.state.basis_amount = round_money(equity / Decimal(self.config.divisions))
        self.state.round_anchor_date = soxx.date
        self.state.round_anchor_equity = equity
        # _append_equity records the close anchor immediately after this method.
        # Using its upcoming sequence excludes an earlier same-day open mark.
        self.round_anchor_path_sequences[self.state.round_id] = len(self.round_path_points) + 1
        self.state.executed_levels.clear()

    def _append_equity(self, soxx: PriceBar, soxl: PriceBar) -> None:
        equity = self._portfolio_value(soxx.close, soxl.close)
        soxx_value = round_money(self.state.soxx_shares * soxx.close)
        soxl_value = round_money(self.state.soxl_shares * soxl.close)
        soxx_weight = (soxx_value / equity * Decimal("100")) if equity > ZERO else ZERO
        soxl_weight = (soxl_value / equity * Decimal("100")) if equity > ZERO else ZERO
        cash_weight = (self.state.cash / equity * Decimal("100")) if equity > ZERO else ZERO
        effective_leverage = (soxx_weight + soxl_weight * Decimal("3")) / Decimal("100")
        soxx_drawdown = (
            ((soxx.close / self.state.peak_price) - ONE) * Decimal("100")
            if self.state.peak_price > ZERO
            else ZERO
        )
        self.equity_curve.append({
            "date": soxx.date,
            "equity": equity,
            "soxx_open": soxx.open,
            "soxx_high": soxx.high,
            "soxx_low": soxx.low,
            "soxx_close": soxx.close,
            "soxl_open": soxl.open,
            "soxl_high": soxl.high,
            "soxl_low": soxl.low,
            "soxl_close": soxl.close,
            "cash": self.state.cash,
            "soxx_shares": self.state.soxx_shares,
            "soxl_shares": self.state.soxl_shares,
            "soxx_value": soxx_value,
            "soxl_value": soxl_value,
            "soxx_weight": round_rate(soxx_weight),
            "soxl_weight": round_rate(soxl_weight),
            "cash_weight": round_rate(cash_weight),
            "effective_leverage": round_rate(effective_leverage),
            "soxx_drawdown": round_rate(soxx_drawdown),
            "portfolio_return": round_rate(((equity / self.config.principal) - ONE) * Decimal("100")),
            "peak_price": self.state.peak_price,
            "basis_amount": self.state.basis_amount,
            "round_id": self.state.round_id,
            "executed_stage_count": len(self.state.executed_levels),
        })
        self._record_round_path_point(
            date_value=soxx.date,
            phase="close_mark",
            soxx_price=soxx.close,
            soxl_price=soxl.close,
        )

    def _attach_round_path_metrics(self) -> None:
        for round_result in self.rounds:
            anchor_sequence = self.round_anchor_path_sequences.get(round_result.round_id, 0)
            points = [
                point for point in self.round_path_points
                if point["round_id"] == round_result.round_id
                and point["sequence"] >= anchor_sequence
                and round_result.start_date <= point["date"] <= round_result.end_date
            ]
            if not points:
                continue
            peak = decimal(points[0]["equity"])
            peak_date = str(points[0]["date"])
            max_drawdown = ZERO
            max_peak_date = peak_date
            max_trough_date = peak_date
            min_from_start = ZERO
            for point in points:
                equity = decimal(point["equity"])
                if equity >= peak:
                    peak = equity
                    peak_date = str(point["date"])
                drawdown = ((equity / peak) - ONE) * Decimal("100") if peak > ZERO else ZERO
                if drawdown < max_drawdown:
                    max_drawdown = drawdown
                    max_peak_date = peak_date
                    max_trough_date = str(point["date"])
                from_start = (
                    ((equity / round_result.start_portfolio_value) - ONE) * Decimal("100")
                    if round_result.start_portfolio_value > ZERO
                    else ZERO
                )
                min_from_start = min(min_from_start, from_start)
            round_result.max_soxx_drawdown = round_rate(min(decimal(point["soxx_drawdown"]) for point in points))
            round_result.max_portfolio_drawdown = round_rate(max_drawdown)
            round_result.max_loss_from_start = round_rate(min_from_start)
            round_result.max_soxl_weight = round_rate(max(decimal(point["soxl_weight"]) for point in points))
            round_result.max_effective_leverage = round_rate(max(decimal(point["effective_leverage"]) for point in points))
            round_result.mdd_peak_date = max_peak_date
            round_result.mdd_trough_date = max_trough_date

    def _drawdown_buckets(self) -> list[dict]:
        definitions = [
            ("0% ~ -5%", ZERO, Decimal("-5")),
            ("-5% ~ -10%", Decimal("-5"), Decimal("-10")),
            ("-10% ~ -15%", Decimal("-10"), Decimal("-15")),
            ("-15% ~ -20%", Decimal("-15"), Decimal("-20")),
            ("-20% ~ -30%", Decimal("-20"), Decimal("-30")),
            ("-30% ~ -40%", Decimal("-30"), Decimal("-40")),
            ("-40% ~ -50%", Decimal("-40"), Decimal("-50")),
            ("-50% ~ -60%", Decimal("-50"), Decimal("-60")),
            ("-60% 이하", Decimal("-60"), None),
        ]
        rows: list[dict] = []
        for label, upper, lower in definitions:
            points = []
            for point in self.equity_curve:
                value = decimal(point["soxx_drawdown"])
                if lower is None:
                    matched = value <= upper
                elif upper == ZERO:
                    matched = lower < value <= upper
                else:
                    matched = lower < value <= upper
                if matched:
                    points.append(point)
            if not points:
                rows.append({"bucket": label, "trading_days": 0, "avg_soxx_weight": None, "avg_soxl_weight": None, "avg_cash_weight": None, "avg_effective_leverage": None, "avg_portfolio_return": None})
                continue
            count = Decimal(len(points))
            rows.append({
                "bucket": label,
                "trading_days": len(points),
                "avg_soxx_weight": round_rate(sum((decimal(item["soxx_weight"]) for item in points), ZERO) / count),
                "avg_soxl_weight": round_rate(sum((decimal(item["soxl_weight"]) for item in points), ZERO) / count),
                "avg_cash_weight": round_rate(sum((decimal(item["cash_weight"]) for item in points), ZERO) / count),
                "avg_effective_leverage": round_rate(sum((decimal(item["effective_leverage"]) for item in points), ZERO) / count),
                "avg_portfolio_return": round_rate(sum((decimal(item["portfolio_return"]) for item in points), ZERO) / count),
            })
        return rows

    def run(self) -> dict:
        first_soxx, first_soxl = self.pairs[0]
        self._initial_entry(first_soxx, first_soxl)
        self._append_equity(first_soxx, first_soxl)

        for soxx, soxl in self.pairs[1:]:
            recovered_open = self._recover_to_soxx(soxx, soxl, "open")
            if not recovered_open:
                self._convert_to_soxl(soxx, soxl, "open")
            self._record_round_path_point(
                date_value=soxx.date,
                phase="open_mark",
                soxx_price=soxx.open,
                soxl_price=soxl.open,
            )

            recovered_close = self._recover_to_soxx(soxx, soxl, "close")
            if not recovered_close:
                self._convert_to_soxl(soxx, soxl, "close")

            self._update_peak(soxx, soxl)
            self._append_equity(soxx, soxl)

        self._attach_round_path_metrics()
        metrics, monthly_returns, yearly_returns = calculate_equity_performance(
            self.equity_curve,
            self.config.principal,
            self.config.annual_risk_free_rate,
        )
        ending_equity = decimal(self.equity_curve[-1]["equity"])
        completed_returns = [item.return_pct for item in self.rounds]
        completed_durations = [Decimal(item.recovery_trading_days) for item in self.rounds]
        max_soxl_weight = max((decimal(point["soxl_weight"]) for point in self.round_path_points), default=ZERO)
        avg_soxl_weight = sum((decimal(point["soxl_weight"]) for point in self.equity_curve), ZERO) / Decimal(len(self.equity_curve))
        max_leverage = max((decimal(point["effective_leverage"]) for point in self.round_path_points), default=ZERO)
        avg_leverage = sum((decimal(point["effective_leverage"]) for point in self.equity_curve), ZERO) / Decimal(len(self.equity_curve))
        exhaustion_values = [item.exhaustion_drawdown for item in self.rounds if item.exhaustion_drawdown is not None]
        if self.state.round_exhaustion_drawdown is not None:
            exhaustion_values.append(self.state.round_exhaustion_drawdown)

        conversion_step_counts = [item.number_of_conversion_steps for item in self.rounds]
        active_round_conversion_steps = self.state.round_conversion_steps
        if active_round_conversion_steps > 0:
            conversion_step_counts.append(active_round_conversion_steps)

        strategy_metrics = {
            "total_rounds": len(self.rounds),
            "average_round_trading_days": round_rate(sum(completed_durations, ZERO) / Decimal(len(completed_durations))) if completed_durations else None,
            "median_round_trading_days": round_rate(_median(completed_durations)) if completed_durations else None,
            "longest_round_trading_days": int(max(completed_durations)) if completed_durations else None,
            "average_round_return": round_rate(sum(completed_returns, ZERO) / Decimal(len(completed_returns))) if completed_returns else None,
            "worst_round_return": round_rate(min(completed_returns)) if completed_returns else None,
            "max_soxl_weight": round_rate(max_soxl_weight),
            "average_soxl_weight": round_rate(avg_soxl_weight),
            "max_effective_leverage": round_rate(max_leverage),
            "average_effective_leverage": round_rate(avg_leverage),
            "soxx_exhausted": bool(exhaustion_values),
            "first_exhaustion_drawdown": round_rate(exhaustion_values[0]) if exhaustion_values else None,
            "worst_exhaustion_drawdown": round_rate(min(exhaustion_values)) if exhaustion_values else None,
            "active_round_conversion_steps": active_round_conversion_steps,
            "conversion_step_round_count": len(conversion_step_counts),
            "max_conversion_steps_per_round": max(conversion_step_counts, default=0),
            "average_conversion_steps_per_round": round_rate(
                Decimal(sum(conversion_step_counts)) / Decimal(len(conversion_step_counts))
            ) if conversion_step_counts else None,
            "conversion_event_count": self.diagnostics["conversion_events"],
            "recovery_conversion_count": self.diagnostics["recovery_events"],
            "total_transfer_event_count": self.diagnostics["conversion_events"] + self.diagnostics["recovery_events"],
            "executed_step_count": self.diagnostics["executed_steps"],
            "order_count": self.diagnostics["order_count"],
            "max_reached_stage": self.diagnostics["max_reached_stage"],
        }
        first_date = datetime.strptime(self.pairs[0][0].date, "%Y-%m-%d")
        last_date = datetime.strptime(self.pairs[-1][0].date, "%Y-%m-%d")
        return {
            "schema_version": 1,
            "result_type": "previous_high",
            "config": {
                "strategy": "previous_high",
                "principal": self.config.principal,
                "trigger_interval_pct": self.config.trigger_interval_pct,
                "divisions": self.config.divisions,
                "fractional_shares": self.config.fractional_shares,
                "liquidation_offset_pct": self.config.liquidation_offset_pct,
                "slippage_bps": self.config.slippage_bps,
                "commission": self.config.commission,
                "sell_fee_bps": self.config.sell_fee_bps,
                "annual_risk_free_rate": self.config.annual_risk_free_rate,
                "price_basis": self.price_basis,
            },
            "period": {
                "start": self.pairs[0][0].date,
                "end": self.pairs[-1][0].date,
                "trading_days": len(self.pairs),
                "calendar_days": (last_date - first_date).days + 1,
            },
            "summary": {
                "ending_equity": ending_equity,
                "profit_amount": round_money(ending_equity - self.config.principal),
                "profit_rate": metrics["total_return"],
                "completed_rounds": len(self.rounds),
                "execution_count": len(self.trades),
                "order_count": self.diagnostics["order_count"],
                "cash_balance": self.state.cash,
                "soxx_shares": self.state.soxx_shares,
                "soxl_shares": self.state.soxl_shares,
            },
            "metrics": metrics,
            "strategy_metrics": strategy_metrics,
            "state": {
                "cash": self.state.cash,
                "soxx_shares": self.state.soxx_shares,
                "soxl_shares": self.state.soxl_shares,
                "peak_price": self.state.peak_price,
                "peak_date": self.state.peak_date,
                "peak_portfolio_value": self.state.peak_portfolio_value,
                "basis_amount": self.state.basis_amount,
                "round_id": self.state.round_id,
                "round_anchor_date": self.state.round_anchor_date,
                "executed_levels": sorted(self.state.executed_levels),
            },
            "rounds": [asdict(item) for item in self.rounds],
            "executions": [asdict(item) for item in self.trades],
            "equity_curve": self.equity_curve,
            "monthly_returns": monthly_returns,
            "yearly_returns": yearly_returns,
            "drawdown_buckets": self._drawdown_buckets(),
            "diagnostics": self.diagnostics,
            "warnings": list(dict.fromkeys(self.warnings)),
        }


def run_previous_high_backtest(
    config: PreviousHighConfig,
    soxx_prices: list[PriceBar],
    soxl_prices: list[PriceBar],
    data_diagnostics: dict | None = None,
) -> dict:
    return PreviousHighSimulator(config, soxx_prices, soxl_prices, data_diagnostics).run()
