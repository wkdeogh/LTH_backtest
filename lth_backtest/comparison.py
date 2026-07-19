from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from .data import align_price_series
from .engine import run_backtest
from .models import BacktestConfig, PriceBar
from .performance import calculate_equity_performance
from .precision import ONE, ZERO, decimal, round_market_price, round_money, round_rate
from .previous_high import PreviousHighConfig, _affordable_quantity, run_previous_high_backtest


STRATEGY_META = {
    "previous_high": {"label": "전고점매매법", "color": "#08775b"},
    "infinite_v4": {"label": "무한매수법 V4", "color": "#7651b8"},
    "soxx_buy_hold": {"label": "SOXX Buy & Hold", "color": "#2865d5"},
    "soxl_buy_hold": {"label": "SOXL Buy & Hold", "color": "#c43e45"},
}
HOLD_BENCHMARK_ORDER = ("previous_high", "soxx_buy_hold", "soxl_buy_hold")


def _buy_and_hold(
    symbol: str,
    prices: list[PriceBar],
    principal: Decimal,
    fractional_shares: bool,
    slippage_bps: Decimal,
    commission: Decimal,
    annual_risk_free_rate: Decimal,
) -> dict:
    first = prices[0]
    fill = round_market_price(first.close * (ONE + slippage_bps / Decimal("10000")))
    quantity = _affordable_quantity(principal, fill, commission, fractional_shares)
    if quantity <= ZERO:
        raise ValueError(f"원금이 너무 작아 시작일에 {symbol}을 매수할 수 없습니다.")
    gross = round_money(quantity * fill)
    cash = round_money(principal - gross - commission)
    curve = [
        {
            "date": bar.date,
            "equity": round_money(cash + quantity * bar.close),
            "cash": cash,
            "shares": quantity,
            "close": bar.close,
        }
        for bar in prices
    ]
    metrics, monthly, yearly = calculate_equity_performance(curve, principal, annual_risk_free_rate)
    ending = decimal(curve[-1]["equity"])
    return {
        "symbol": symbol,
        "summary": {
            "ending_equity": ending,
            "profit_amount": round_money(ending - principal),
            "profit_rate": metrics["total_return"],
        },
        "metrics": metrics,
        "monthly_returns": monthly,
        "yearly_returns": yearly,
        "equity_curve": curve,
        "entry": {
            "date": first.date,
            "raw_close": first.close,
            "fill_price": fill,
            "shares": quantity,
            "cash": cash,
            "commission": commission,
        },
    }


def _strategy_payload(label_key: str, summary: dict, metrics: dict) -> dict:
    return {
        "key": label_key,
        **STRATEGY_META[label_key],
        "summary": summary,
        "metrics": metrics,
    }


def run_previous_high_hold_benchmarks(
    previous_config: PreviousHighConfig,
    soxx_prices: list[PriceBar],
    soxl_prices: list[PriceBar],
    *,
    previous_result: dict | None = None,
    data_diagnostics: dict | None = None,
) -> dict:
    """Build exact SOXX/SOXL hold curves for the previous-high dashboard."""
    pairs, alignment = align_price_series(soxx_prices, soxl_prices, "SOXX", "SOXL")
    common_soxx = [left for left, _ in pairs]
    common_soxl = [right for _, right in pairs]
    previous = previous_result or run_previous_high_backtest(
        previous_config, common_soxx, common_soxl, data_diagnostics,
    )
    soxx_hold = _buy_and_hold(
        "SOXX", common_soxx, previous_config.principal, previous_config.fractional_shares,
        previous_config.slippage_bps, previous_config.commission, previous_config.annual_risk_free_rate,
    )
    soxl_hold = _buy_and_hold(
        "SOXL", common_soxl, previous_config.principal, previous_config.fractional_shares,
        previous_config.slippage_bps, previous_config.commission, previous_config.annual_risk_free_rate,
    )
    results = {
        "previous_high": previous,
        "soxx_buy_hold": soxx_hold,
        "soxl_buy_hold": soxl_hold,
    }
    strategies = {
        key: _strategy_payload(key, value["summary"], value["metrics"])
        for key, value in results.items()
    }
    curve_maps = {
        "previous_high": {row["date"]: row["equity"] for row in previous["equity_curve"]},
        "soxx_buy_hold": {row["date"]: row["equity"] for row in soxx_hold["equity_curve"]},
        "soxl_buy_hold": {row["date"]: row["equity"] for row in soxl_hold["equity_curve"]},
    }
    drawdown_maps = {
        "previous_high": {row["date"]: row["drawdown"] for row in previous["equity_curve"]},
        "soxx_buy_hold": {row["date"]: row["drawdown"] for row in soxx_hold["equity_curve"]},
        "soxl_buy_hold": {row["date"]: row["drawdown"] for row in soxl_hold["equity_curve"]},
    }
    equity_curve: list[dict] = []
    for soxx, _ in pairs:
        row: dict = {"date": soxx.date}
        for key in HOLD_BENCHMARK_ORDER:
            row[key] = curve_maps[key][soxx.date]
            row[f"{key}_drawdown"] = drawdown_maps[key][soxx.date]
        equity_curve.append(row)
    return {
        "strategy_order": list(HOLD_BENCHMARK_ORDER),
        "strategies": strategies,
        "equity_curve": equity_curve,
        "alignment": alignment,
    }


def _year_map(rows: list[dict]) -> dict[str, dict]:
    return {str(row["period"]): row for row in rows}


def _comparison_years(strategy_results: dict[str, dict]) -> list[dict]:
    maps = {key: _year_map(value["yearly_returns"]) for key, value in strategy_results.items()}
    years = sorted(set().union(*(set(rows) for rows in maps.values())))
    result: list[dict] = []
    for year in years:
        row: dict = {"year": year}
        for key, rows in maps.items():
            row[key] = rows.get(year, {}).get("return_rate")
        result.append(row)
    return result


def _slice_metrics(rows: list[dict], key: str, risk_free: Decimal) -> dict | None:
    if len(rows) < 2:
        return None
    curve = [{"date": row["date"], "equity": row[key]} for row in rows]
    start = decimal(curve[0]["equity"])
    metrics, _, _ = calculate_equity_performance(curve, start, risk_free)
    return metrics


def _period_comparison(rows: list[dict], risk_free: Decimal) -> list[dict]:
    if len(rows) < 2:
        return []
    boundaries = [0, len(rows) // 3, (len(rows) * 2) // 3, len(rows)]
    periods: list[tuple[str, list[dict], bool | None]] = []
    for index, label in enumerate(("초기 1/3", "중간 1/3", "최근 1/3")):
        start = boundaries[index]
        end = boundaries[index + 1]
        segment = rows[start:end]
        if len(segment) >= 2:
            periods.append((label, segment, None))

    regimes = (
        ("2018 시장 조정", "2018-03-01", "2019-04-30"),
        ("2020 코로나 충격·반등", "2020-02-19", "2020-08-31"),
        ("2022 금리인상·반도체 하락", "2022-01-03", "2022-12-30"),
    )
    for label, start, end in regimes:
        segment = [row for row in rows if start <= row["date"] <= end]
        if len(segment) >= 2:
            periods.append((label, segment, None))

    trough_index = min(
        range(len(rows)),
        key=lambda index: decimal(rows[index]["soxx_buy_hold_drawdown"]),
    )
    if decimal(rows[trough_index]["soxx_buy_hold_drawdown"]) < ZERO:
        peak_index = max(
            range(trough_index + 1),
            key=lambda index: decimal(rows[index]["soxx_buy_hold"]),
        )
        peak_equity = decimal(rows[peak_index]["soxx_buy_hold"])
        recovery_index = next((
            index for index in range(trough_index + 1, len(rows))
            if decimal(rows[index]["soxx_buy_hold"]) >= peak_equity
        ), None)
        recovered = recovery_index is not None
        segment_end = recovery_index if recovery_index is not None else len(rows) - 1
        dynamic_segment = rows[peak_index:segment_end + 1]
        if len(dynamic_segment) >= 2:
            recovery_label = "회복" if recovered else "미회복"
            periods.append((f"데이터 내 SOXX 최대 낙폭·{recovery_label}", dynamic_segment, recovered))

    output: list[dict] = []
    for label, segment, recovered in periods:
        item = {
            "period": label,
            "start": segment[0]["date"],
            "end": segment[-1]["date"],
            "recovered": recovered,
        }
        for key in STRATEGY_META:
            metrics = _slice_metrics(segment, key, risk_free)
            item[key] = {
                "total_return": metrics["total_return"],
                "cagr": metrics["cagr"],
                "close_mdd": metrics["close_mdd"],
                "calmar_ratio": metrics["calmar_ratio"],
            } if metrics else None
        output.append(item)
    return output


def _bear_market_hypothesis(periods: list[dict], previous_mdd: Decimal, soxx_mdd: Decimal) -> dict:
    """Build an observational risk check without implying causal evidence."""
    selected = next((item for item in periods if str(item["period"]).startswith("2022 ")), None)
    if selected is None:
        selected = next((
            item for item in periods
            if str(item["period"]).startswith("데이터 내 SOXX 최대 낙폭")
        ), None)

    if selected is not None:
        scope = str(selected["period"])
        scope_start = selected["start"]
        scope_end = selected["end"]
        scoped_previous_mdd = decimal(selected["previous_high"]["close_mdd"])
        scoped_soxx_mdd = decimal(selected["soxx_buy_hold"]["close_mdd"])
        used_overall_period = False
    else:
        scope = "대표 약세장 구간 없음 · 전체 기간 MDD 비교"
        scope_start = None
        scope_end = None
        scoped_previous_mdd = previous_mdd
        scoped_soxx_mdd = soxx_mdd
        used_overall_period = True

    risk_increase = abs(scoped_previous_mdd) - abs(scoped_soxx_mdd)
    return {
        "id": 4,
        "label": "대표 약세장에서 전고점매매법 MDD가 SOXX보다 큰가 (위험 증가 관찰)",
        "passed": risk_increase > ZERO,
        "difference_pct_points": round_rate(risk_increase),
        "scope": scope,
        "scope_start": scope_start,
        "scope_end": scope_end,
        "used_overall_period": used_overall_period,
        "previous_high_mdd": round_rate(scoped_previous_mdd),
        "soxx_mdd": round_rate(scoped_soxx_mdd),
        "causal_claim": False,
    }


def _round_recovery_hypothesis(previous: dict) -> dict:
    rounds = previous.get("rounds", [])
    completed_count = len(rounds)
    positive_count = sum(1 for item in rounds if decimal(item["return_pct"]) > ZERO)
    average_return = previous["strategy_metrics"].get("average_round_return")
    worst_return = previous["strategy_metrics"].get("worst_round_return")
    recovery_events = int(previous.get("diagnostics", {}).get("recovery_events", 0))
    average_is_positive = average_return is not None and decimal(average_return) > ZERO
    positive_rate = (
        round_rate(Decimal(positive_count) / Decimal(completed_count) * Decimal("100"))
        if completed_count
        else None
    )
    return {
        "id": 5,
        "label": "회복 청산·SOXX 복귀 후 완료 라운드 평균 성과가 양(+)인가 (관찰 진단)",
        "passed": recovery_events > 0 and average_is_positive,
        "difference_pct_points": round_rate(decimal(average_return)) if average_return is not None else None,
        "completed_rounds": completed_count,
        "positive_completed_rounds": positive_count,
        "positive_completed_round_rate": positive_rate,
        "average_round_return": average_return,
        "worst_round_return": worst_return,
        "recovery_conversion_count": recovery_events,
        "causal_claim": False,
        "interpretation": "완료 라운드의 관찰 성과이며 회복 청산 구조의 인과 효과를 증명하지 않습니다.",
    }


def run_strategy_comparison(
    previous_config: PreviousHighConfig,
    soxx_prices: list[PriceBar],
    soxl_prices: list[PriceBar],
    *,
    v4_split_count: int = 20,
    v4_compounding_type: str = "compound",
    v4_sell_percent: Decimal | None = None,
    v4_fill_model: str = "intraday_high",
    v4_initial_entry: str = "web_loc",
    v4_first_buy_buffer_percent: Decimal = Decimal("12"),
    result_type: str = "comparison",
    data_diagnostics: dict | None = None,
) -> dict:
    pairs, alignment = align_price_series(soxx_prices, soxl_prices, "SOXX", "SOXL")
    common_soxx = [left for left, _ in pairs]
    common_soxl = [right for _, right in pairs]
    previous = run_previous_high_backtest(previous_config, common_soxx, common_soxl, data_diagnostics)

    soxx_hold = _buy_and_hold(
        "SOXX", common_soxx, previous_config.principal, previous_config.fractional_shares,
        previous_config.slippage_bps, previous_config.commission, previous_config.annual_risk_free_rate,
    )
    soxl_hold = _buy_and_hold(
        "SOXL", common_soxl, previous_config.principal, previous_config.fractional_shares,
        previous_config.slippage_bps, previous_config.commission, previous_config.annual_risk_free_rate,
    )
    v4_config = BacktestConfig(
        symbol="SOXL",
        split_count=v4_split_count,
        principal=previous_config.principal,
        compounding_type=v4_compounding_type,
        sell_percent=v4_sell_percent,
        fill_model=v4_fill_model,
        initial_entry=v4_initial_entry,
        first_buy_buffer_percent=v4_first_buy_buffer_percent,
        slippage_bps=previous_config.slippage_bps,
        commission=previous_config.commission,
        sell_fee_bps=previous_config.sell_fee_bps,
        annual_risk_free_rate=previous_config.annual_risk_free_rate,
    )
    v4 = run_backtest(v4_config, common_soxl, data_diagnostics)
    v4_metrics, v4_monthly, v4_yearly = calculate_equity_performance(
        v4.equity_curve, previous_config.principal, previous_config.annual_risk_free_rate,
    )
    v4_result = {
        "summary": {
            "ending_equity": v4.summary["ending_equity"],
            "profit_amount": v4.summary["profit_amount"],
            "profit_rate": v4_metrics["total_return"],
        },
        "metrics": v4_metrics,
        "monthly_returns": v4_monthly,
        "yearly_returns": v4_yearly,
        "equity_curve": v4.equity_curve,
    }

    strategy_results = {
        "previous_high": previous,
        "infinite_v4": v4_result,
        "soxx_buy_hold": soxx_hold,
        "soxl_buy_hold": soxl_hold,
    }
    strategies = {
        key: _strategy_payload(key, value["summary"], value["metrics"])
        for key, value in strategy_results.items()
    }
    maps = {
        "previous_high": {row["date"]: row for row in previous["equity_curve"]},
        "infinite_v4": {row["date"]: row for row in v4.equity_curve},
        "soxx_buy_hold": {row["date"]: row for row in soxx_hold["equity_curve"]},
        "soxl_buy_hold": {row["date"]: row for row in soxl_hold["equity_curve"]},
    }
    comparison_curve: list[dict] = []
    for soxx, _ in pairs:
        date_value = soxx.date
        row = {"date": date_value}
        for key, values in maps.items():
            point = values[date_value]
            row[key] = point["equity"]
            row[f"{key}_drawdown"] = point["drawdown"]
        comparison_curve.append(row)

    yearly_rows = _comparison_years(strategy_results)
    comparable_years = [
        row for row in yearly_rows
        if row["previous_high"] is not None and row["soxx_buy_hold"] is not None and row["infinite_v4"] is not None
    ]
    previous_wins_soxx = sum(1 for row in comparable_years if decimal(row["previous_high"]) > decimal(row["soxx_buy_hold"]))
    previous_wins_v4 = sum(1 for row in comparable_years if decimal(row["previous_high"]) > decimal(row["infinite_v4"]))
    soxx_yearly_edges = [
        (str(row["year"]), decimal(row["previous_high"]) - decimal(row["soxx_buy_hold"]))
        for row in comparable_years
    ]
    v4_yearly_edges = [
        (str(row["year"]), decimal(row["previous_high"]) - decimal(row["infinite_v4"]))
        for row in comparable_years
    ]
    best_soxx_edge = max(soxx_yearly_edges, key=lambda item: item[1], default=(None, None))
    worst_soxx_edge = min(soxx_yearly_edges, key=lambda item: item[1], default=(None, None))
    best_v4_edge = max(v4_yearly_edges, key=lambda item: item[1], default=(None, None))
    worst_v4_edge = min(v4_yearly_edges, key=lambda item: item[1], default=(None, None))
    previous_return = decimal(previous["metrics"]["total_return"])
    soxx_return = decimal(soxx_hold["metrics"]["total_return"])
    soxx_mdd = decimal(soxx_hold["metrics"]["close_mdd"])
    soxl_mdd = decimal(soxl_hold["metrics"]["close_mdd"])
    previous_mdd = decimal(previous["metrics"]["close_mdd"])
    v4_return = decimal(v4_metrics["total_return"])
    period_analysis = _period_comparison(comparison_curve, previous_config.annual_risk_free_rate)
    hypothesis_checks = [
        {"id": 1, "label": "전고점매매법 총수익률이 V4보다 높은가", "passed": previous_return > v4_return, "difference_pct_points": round_rate(previous_return - v4_return)},
        {"id": 2, "label": "전고점매매법이 SOXX보다 초과수익을 냈는가", "passed": previous_return > soxx_return, "difference_pct_points": round_rate(previous_return - soxx_return)},
        {"id": 3, "label": "전고점매매법 MDD가 SOXL 장기보유보다 낮은가", "passed": abs(previous_mdd) < abs(soxl_mdd), "difference_pct_points": round_rate(abs(soxl_mdd) - abs(previous_mdd))},
        _bear_market_hypothesis(period_analysis, previous_mdd, soxx_mdd),
        _round_recovery_hypothesis(previous),
    ]
    comparison = {
        "strategy_order": list(STRATEGY_META),
        "strategies": strategies,
        "equity_curve": comparison_curve,
        "yearly_returns": yearly_rows,
        "period_analysis": period_analysis,
        "annual_outperformance": {
            "comparable_years": len(comparable_years),
            "previous_high_over_soxx_years": previous_wins_soxx,
            "previous_high_over_soxx_rate": round_rate(Decimal(previous_wins_soxx) / Decimal(len(comparable_years)) * Decimal("100")) if comparable_years else None,
            "previous_high_over_v4_years": previous_wins_v4,
            "previous_high_over_v4_rate": round_rate(Decimal(previous_wins_v4) / Decimal(len(comparable_years)) * Decimal("100")) if comparable_years else None,
            "best_year_vs_soxx": best_soxx_edge[0],
            "best_year_vs_soxx_pct_points": round_rate(best_soxx_edge[1]) if best_soxx_edge[1] is not None else None,
            "worst_year_vs_soxx": worst_soxx_edge[0],
            "worst_year_vs_soxx_pct_points": round_rate(worst_soxx_edge[1]) if worst_soxx_edge[1] is not None else None,
            "best_year_vs_v4": best_v4_edge[0],
            "best_year_vs_v4_pct_points": round_rate(best_v4_edge[1]) if best_v4_edge[1] is not None else None,
            "worst_year_vs_v4": worst_v4_edge[0],
            "worst_year_vs_v4_pct_points": round_rate(worst_v4_edge[1]) if worst_v4_edge[1] is not None else None,
        },
        "hypothesis_checks": hypothesis_checks,
        "alignment": alignment,
    }
    previous["result_type"] = result_type
    previous["comparison"] = comparison
    previous["market_data"] = {
        "SOXX": [asdict(item) for item in common_soxx],
        "SOXL": [asdict(item) for item in common_soxl],
    }
    previous["config"]["v4_split_count"] = v4_split_count
    previous["config"]["v4_compounding_type"] = v4_compounding_type
    previous["config"]["v4_sell_percent"] = v4_sell_percent
    previous["config"]["v4_effective_sell_percent"] = v4_config.effective_sell_percent
    previous["config"]["v4_fill_model"] = v4_fill_model
    previous["config"]["v4_initial_entry"] = v4_initial_entry
    previous["config"]["v4_first_buy_buffer_percent"] = v4_first_buy_buffer_percent
    previous["diagnostics"]["comparison_alignment"] = alignment
    if previous_config.fractional_shares:
        previous["warnings"].append(
            "소수점 수량 옵션은 전고점매매법과 Buy & Hold 비교선에만 적용됩니다. "
            "무한매수법 V4는 기존 엔진 규칙대로 정수 주식 수량을 유지합니다."
        )
    return previous
