from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .data import align_price_series
from .models import PriceBar
from .precision import ZERO, decimal, round_rate
from .previous_high import PreviousHighConfig, run_previous_high_backtest


DEFAULT_INTERVALS = (
    Decimal("2.5"), Decimal("3"), Decimal("4"), Decimal("5"),
    Decimal("6"), Decimal("7.5"), Decimal("10"),
)
DEFAULT_DIVISIONS = (10, 15, 20, 25, 30, 40)


def _validate_candidates(
    intervals: list[Decimal] | tuple[Decimal, ...],
    divisions: list[int] | tuple[int, ...],
) -> tuple[list[Decimal], list[int]]:
    interval_values = [decimal(value) for value in intervals]
    division_values = [int(value) for value in divisions]
    if not interval_values or not division_values:
        raise ValueError("매매 간격과 분할 수 후보가 각각 1개 이상 필요합니다.")
    if len(interval_values) > 20 or len(division_values) > 20:
        raise ValueError("파라미터 후보는 각 축당 최대 20개까지 지원합니다.")
    if len(set(interval_values)) != len(interval_values) or len(set(division_values)) != len(division_values):
        raise ValueError("파라미터 후보에 중복값이 있습니다.")
    if any(value <= ZERO or value >= Decimal("100") for value in interval_values):
        raise ValueError("매매 간격 후보는 0보다 크고 100보다 작아야 합니다.")
    if any(value < 2 or value > 500 for value in division_values):
        raise ValueError("분할 수 후보는 2 이상 500 이하여야 합니다.")
    return sorted(interval_values), sorted(division_values)


def _period_slices(pairs: list[tuple[PriceBar, PriceBar]]) -> list[tuple[str, list[PriceBar], list[PriceBar]]]:
    boundaries = [0, len(pairs) // 3, (len(pairs) * 2) // 3, len(pairs)]
    result: list[tuple[str, list[PriceBar], list[PriceBar]]] = []
    for index, label in enumerate(("초기 1/3", "중간 1/3", "최근 1/3")):
        segment = pairs[boundaries[index]:boundaries[index + 1]]
        if len(segment) >= 2:
            result.append((label, [left for left, _ in segment], [right for _, right in segment]))
    return result


def _percentile_scores(rows: list[dict], period_names: list[str]) -> None:
    count = len(rows)
    if count == 1:
        rows[0]["robustness_score"] = Decimal("100")
        return
    score_map: dict[tuple[str, str, str, str], Decimal] = {}
    for period in period_names:
        # Rank CAGR and Calmar independently, then combine them with equal
        # weight.  A tuple comparison would be lexicographic and make CAGR
        # matter only when Calmar is tied, contrary to the documented method.
        for metric in ("calmar_ratio", "cagr"):
            values = [decimal(row["period_metrics"][period][metric]) for row in rows]
            for row, value in zip(rows, values):
                key = (str(row["trigger_interval_pct"]), str(row["divisions"]))
                lower_count = sum(1 for candidate in values if candidate < value)
                # Tie-aware mid-rank keeps an all-equal plateau neutral at 50
                # while preserving 0 and 100 for unique worst/best values.
                equal_count = sum(1 for candidate in values if candidate == value)
                mid_rank = Decimal(lower_count) + (Decimal(equal_count - 1) / Decimal("2"))
                score_map[key[0], key[1], period, metric] = mid_rank / Decimal(count - 1) * Decimal("100")
    for row in rows:
        key = (str(row["trigger_interval_pct"]), str(row["divisions"]))
        component_scores = [
            score_map[key[0], key[1], period, metric]
            for period in period_names
            for metric in ("calmar_ratio", "cagr")
        ]
        row["robustness_score"] = round_rate(
            sum(component_scores, ZERO) / Decimal(len(component_scores))
        )


def _attach_neighbor_stability(rows: list[dict], intervals: list[Decimal], divisions: list[int]) -> None:
    indexed = {(decimal(row["trigger_interval_pct"]), int(row["divisions"])): row for row in rows}
    for row in rows:
        interval = decimal(row["trigger_interval_pct"])
        division = int(row["divisions"])
        interval_index = intervals.index(interval)
        division_index = divisions.index(division)
        neighbor_keys: list[tuple[Decimal, int]] = []
        for offset in (-1, 1):
            if 0 <= interval_index + offset < len(intervals):
                neighbor_keys.append((intervals[interval_index + offset], division))
            if 0 <= division_index + offset < len(divisions):
                neighbor_keys.append((interval, divisions[division_index + offset]))
        neighbors = [indexed[key] for key in neighbor_keys if key in indexed]
        if not neighbors:
            row["neighbor_count"] = 0
            row["neighbor_cagr_spread"] = ZERO
            row["neighbor_calmar_spread"] = ZERO
            row["stability_score"] = row["robustness_score"]
            continue
        cagr = decimal(row["cagr"])
        calmar = decimal(row["calmar_ratio"])
        cagr_spread = sum((abs(decimal(item["cagr"]) - cagr) for item in neighbors), ZERO) / Decimal(len(neighbors))
        calmar_spread = sum((abs(decimal(item["calmar_ratio"]) - calmar) for item in neighbors), ZERO) / Decimal(len(neighbors))
        penalty = min(cagr_spread + calmar_spread * Decimal("2"), Decimal("50"))
        row["neighbor_count"] = len(neighbors)
        row["neighbor_cagr_spread"] = round_rate(cagr_spread)
        row["neighbor_calmar_spread"] = round_rate(calmar_spread)
        row["stability_score"] = round_rate(max(decimal(row["robustness_score"]) - penalty, ZERO))


def _matrix(rows: list[dict], intervals: list[Decimal], divisions: list[int], key: str) -> list[list[Decimal]]:
    indexed = {(decimal(row["trigger_interval_pct"]), int(row["divisions"])): decimal(row[key]) for row in rows}
    return [[indexed[(interval, division)] for division in divisions] for interval in intervals]


def run_parameter_sweep(
    base_config: PreviousHighConfig,
    soxx_prices: list[PriceBar],
    soxl_prices: list[PriceBar],
    intervals: list[Decimal] | tuple[Decimal, ...] = DEFAULT_INTERVALS,
    divisions: list[int] | tuple[int, ...] = DEFAULT_DIVISIONS,
    *,
    include_subperiods: bool = True,
    data_diagnostics: dict | None = None,
) -> dict:
    interval_values, division_values = _validate_candidates(intervals, divisions)
    pairs, alignment = align_price_series(soxx_prices, soxl_prices, "SOXX", "SOXL")
    common_soxx = [left for left, _ in pairs]
    common_soxl = [right for _, right in pairs]
    periods = [("전체", common_soxx, common_soxl)]
    if include_subperiods:
        periods.extend(_period_slices(pairs))
    rows: list[dict] = []
    resolved_price_basis = "unknown"

    for interval in interval_values:
        for division in division_values:
            config = replace(base_config, trigger_interval_pct=interval, divisions=division)
            period_metrics: dict[str, dict] = {}
            full_result: dict | None = None
            for period_name, period_soxx, period_soxl in periods:
                result = run_previous_high_backtest(config, period_soxx, period_soxl, data_diagnostics)
                if period_name == "전체":
                    full_result = result
                period_metrics[period_name] = {
                    "ending_equity": result["summary"]["ending_equity"],
                    "total_return": result["metrics"]["total_return"],
                    "cagr": result["metrics"]["cagr"],
                    "close_mdd": result["metrics"]["close_mdd"],
                    "calmar_ratio": result["metrics"]["calmar_ratio"],
                    "sharpe_ratio": result["metrics"]["sharpe_ratio"],
                }
            assert full_result is not None
            resolved_price_basis = str(full_result["config"]["price_basis"])
            rows.append({
                "trigger_interval_pct": interval,
                "divisions": division,
                "ending_equity": full_result["summary"]["ending_equity"],
                "total_return": full_result["metrics"]["total_return"],
                "cagr": full_result["metrics"]["cagr"],
                "close_mdd": full_result["metrics"]["close_mdd"],
                "calmar_ratio": full_result["metrics"]["calmar_ratio"],
                "sharpe_ratio": full_result["metrics"]["sharpe_ratio"],
                "max_soxl_weight": full_result["strategy_metrics"]["max_soxl_weight"],
                "max_effective_leverage": full_result["strategy_metrics"]["max_effective_leverage"],
                "completed_rounds": full_result["summary"]["completed_rounds"],
                "conversion_events": full_result["strategy_metrics"]["conversion_event_count"],
                "period_metrics": period_metrics,
            })

    period_names = [name for name, _, _ in periods]
    _percentile_scores(rows, period_names)
    _attach_neighbor_stability(rows, interval_values, division_values)
    stable_regions = sorted(
        rows,
        key=lambda row: (decimal(row["stability_score"]), decimal(row["robustness_score"])),
        reverse=True,
    )[: min(5, len(rows))]
    baseline = next(
        (row for row in rows if decimal(row["trigger_interval_pct"]) == Decimal("5") and int(row["divisions"]) == 20),
        None,
    )
    return {
        "schema_version": 1,
        "result_type": "parameter_sweep",
        "config": {
            "principal": base_config.principal,
            "fractional_shares": base_config.fractional_shares,
            "liquidation_offset_pct": base_config.liquidation_offset_pct,
            "slippage_bps": base_config.slippage_bps,
            "commission": base_config.commission,
            "sell_fee_bps": base_config.sell_fee_bps,
            "annual_risk_free_rate": base_config.annual_risk_free_rate,
            "price_basis": resolved_price_basis,
        },
        "axes": {"intervals": interval_values, "divisions": division_values},
        "periods": [
            {"name": name, "start": soxx[0].date, "end": soxx[-1].date, "trading_days": len(soxx)}
            for name, soxx, _ in periods
        ],
        "rows": rows,
        "heatmaps": {
            "cagr": _matrix(rows, interval_values, division_values, "cagr"),
            "close_mdd": _matrix(rows, interval_values, division_values, "close_mdd"),
            "calmar_ratio": _matrix(rows, interval_values, division_values, "calmar_ratio"),
        },
        "baseline": baseline,
        "stable_regions": stable_regions,
        "alignment": alignment,
        "methodology": {
            "selection": (
                "전체와 3개 독립 하위기간의 Calmar·CAGR 순위 및 인접 조합 변화폭을 함께 평가"
                if include_subperiods
                else "전체 기간의 Calmar·CAGR 순위 및 인접 조합 변화폭을 평가"
            ),
            "warning": "단일 최고 CAGR을 최적값으로 확정하지 말고 높은 안정성 점수가 주변 조합에서도 유지되는지 확인하세요.",
            "subperiod_validation": include_subperiods,
            "subperiod_reset": (
                "각 1/3 구간은 동일 원금으로 전략 상태를 초기화하여 독립 실행"
                if include_subperiods
                else "기간 분할 검증을 사용하지 않음"
            ),
        },
    }
