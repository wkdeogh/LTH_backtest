from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .engine import run_backtest
from .models import BacktestConfig, BacktestResult, PriceBar
from .precision import ZERO, decimal, mean_decimal, round_money, round_rate, round_t


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _average(values: list[Decimal]) -> Decimal | None:
    return mean_decimal(values) if values else None


def _average_rate(values: list[Decimal]) -> Decimal | None:
    value = _average(values)
    return round_rate(value) if value is not None else None


def _median_rate(values: list[Decimal]) -> Decimal | None:
    value = _median(values)
    return round_rate(value) if value is not None else None


def _maximum_t(result: BacktestResult) -> Decimal:
    candidates = [ZERO]
    candidates.extend(decimal(point["t_value"]) for point in result.equity_curve)
    for execution in result.executions:
        candidates.extend((execution.t_before, execution.t_after))
    return round_t(max(candidates))


def _config_payload(config: BacktestConfig) -> dict:
    return {
        "symbol": config.symbol,
        "split_count": config.split_count,
        "principal": config.principal,
        "compounding_type": config.compounding_type,
        "sell_percent": config.effective_sell_percent,
        "fill_model": config.fill_model,
        "initial_entry": "moc",
        "first_buy_buffer_percent": config.first_buy_buffer_percent,
        "slippage_bps": config.slippage_bps,
        "commission": config.commission,
        "sell_fee_bps": config.sell_fee_bps,
    }


def run_round_start_analysis(
    config: BacktestConfig,
    prices: list[PriceBar],
    data_diagnostics: dict | None = None,
) -> dict:
    """Run one independent round from every available trading day.

    Each sample buys its first unit at that start day's close, uses the same
    order engine as the normal backtest, and stops immediately after the first
    completed liquidation. Samples that do not finish are marked to market on
    the analysis end date and excluded from completed-round return/duration
    aggregates.
    """
    if not prices:
        raise ValueError("시작일별 라운드 분석에는 가격 데이터가 필요합니다.")

    rows: list[dict] = []
    for start_index, start_day in enumerate(prices):
        result = run_backtest(
            config,
            prices[start_index:],
            stop_after_completed_rounds=1,
        )
        completed = bool(result.rounds)
        completed_round = result.rounds[0] if completed else None
        last_point = result.equity_curve[-1]
        executions = result.executions
        ending_equity = decimal(result.summary["ending_equity"])
        profit_amount = round_money(ending_equity - config.principal)
        profit_rate = round_rate((profit_amount / config.principal) * Decimal("100"))
        last_observed_at = str(result.period["end"])
        calendar_days = (
            datetime.strptime(last_observed_at, "%Y-%m-%d")
            - datetime.strptime(start_day.date, "%Y-%m-%d")
        ).days + 1

        rows.append({
            "start_date": start_day.date,
            "completed": completed,
            "status": "completed" if completed else "incomplete",
            "end_date": completed_round.ended_at if completed_round else None,
            "last_observed_at": last_observed_at,
            "calendar_days": completed_round.calendar_days if completed_round else calendar_days,
            "trading_days": completed_round.trading_days if completed_round else len(result.equity_curve),
            "starting_equity": config.principal,
            "ending_equity": ending_equity,
            "profit_amount": profit_amount,
            "profit_rate": profit_rate,
            "close_mdd": decimal(result.metrics["close_mdd"]),
            "max_t_value": _maximum_t(result),
            "ending_t_value": decimal(last_point["t_value"]),
            "reverse_entered": int(result.diagnostics["reverse_entries"]) > 0,
            "reverse_entries": int(result.diagnostics["reverse_entries"]),
            "reverse_returns": int(result.diagnostics["reverse_returns"]),
            "ending_mode": str(last_point["mode"]),
            "execution_count": len(executions),
            "buy_count": sum(1 for execution in executions if execution.side == "buy"),
            "sell_count": sum(1 for execution in executions if execution.side == "sell"),
            "intraday_high_only_fills": int(result.diagnostics["intraday_high_only_fills"]),
            "ending_position_qty": int(result.state["position_qty"]),
            "max_position_qty": max(int(point["position_qty"]) for point in result.equity_curve),
            "total_fees": round_money(sum((execution.fees for execution in executions), ZERO)),
        })

    completed_rows = [row for row in rows if row["completed"]]
    completed_profit_rates = [decimal(row["profit_rate"]) for row in completed_rows]
    completed_calendar_days = [decimal(row["calendar_days"]) for row in completed_rows]
    completed_trading_days = [decimal(row["trading_days"]) for row in completed_rows]
    all_mdds = [decimal(row["close_mdd"]) for row in rows]
    all_max_t = [decimal(row["max_t_value"]) for row in rows]
    all_buy_counts = [decimal(row["buy_count"]) for row in rows]
    all_sell_counts = [decimal(row["sell_count"]) for row in rows]
    all_execution_counts = [decimal(row["execution_count"]) for row in rows]
    sample_count = Decimal(len(rows))
    completed_count = len(completed_rows)
    reverse_count = sum(1 for row in rows if row["reverse_entered"])
    profitable_count = sum(1 for row in completed_rows if decimal(row["profit_rate"]) > ZERO)

    summary = {
        "sample_count": len(rows),
        "completed_count": completed_count,
        "incomplete_count": len(rows) - completed_count,
        "completion_rate": round_rate(Decimal(completed_count) / sample_count * Decimal("100")),
        "profitable_completed_count": profitable_count,
        "completed_win_rate": (
            round_rate(Decimal(profitable_count) / Decimal(completed_count) * Decimal("100"))
            if completed_count else None
        ),
        "avg_profit_rate_completed": _average_rate(completed_profit_rates),
        "median_profit_rate_completed": _median_rate(completed_profit_rates),
        "worst_profit_rate_completed": min(completed_profit_rates) if completed_profit_rates else None,
        "best_profit_rate_completed": max(completed_profit_rates) if completed_profit_rates else None,
        "avg_calendar_days_completed": _average_rate(completed_calendar_days),
        "median_calendar_days_completed": _median_rate(completed_calendar_days),
        "avg_trading_days_completed": _average_rate(completed_trading_days),
        "median_trading_days_completed": _median_rate(completed_trading_days),
        "avg_close_mdd_all": _average_rate(all_mdds),
        "worst_close_mdd_all": min(all_mdds),
        "avg_max_t_value_all": round_t(_average(all_max_t) or ZERO),
        "highest_max_t_value": max(all_max_t),
        "reverse_sample_count": reverse_count,
        "reverse_entry_rate": round_rate(Decimal(reverse_count) / sample_count * Decimal("100")),
        "avg_buy_count_all": _average_rate(all_buy_counts),
        "avg_sell_count_all": _average_rate(all_sell_counts),
        "avg_execution_count_all": _average_rate(all_execution_counts),
        "intraday_high_only_fills": sum(int(row["intraday_high_only_fills"]) for row in rows),
    }

    diagnostics = dict(data_diagnostics or {})
    diagnostics.update({
        "start_date_rule": "CSV에 존재하는 각 거래일",
        "first_entry_rule": "각 시작일 종가 MOC",
        "completion_rule": "보유수량 0이 되는 첫 전량매도일",
        "incomplete_rule": "설정 종료일 종가 평가, 완료 통계에서 제외",
        "mdd_rule": "각 표본의 일별 종가 평가자산 최고점 대비 낙폭",
    })
    return {
        "config": _config_payload(config),
        "period": {
            "start": prices[0].date,
            "end": prices[-1].date,
            "trading_days": len(prices),
        },
        "summary": summary,
        "rows": rows,
        "diagnostics": diagnostics,
    }
