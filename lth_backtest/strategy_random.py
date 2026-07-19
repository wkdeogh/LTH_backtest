from __future__ import annotations

import random
import statistics
from decimal import Decimal
from typing import Callable

from .comparison import STRATEGY_META, run_strategy_comparison
from .models import PriceBar
from .precision import ZERO, decimal, round_money, round_rate, to_primitive
from .previous_high import PreviousHighConfig


MAX_STRATEGY_RANDOM_SAMPLES = 5_000
ProgressCallback = Callable[[int, int, dict], None]


def _filter(prices: list[PriceBar], start_date: str, end_date: str) -> list[PriceBar]:
    return [item for item in prices if start_date <= item.date <= end_date]


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def run_strategy_random_comparison(
    previous_config: PreviousHighConfig,
    soxx_prices: list[PriceBar],
    soxl_prices: list[PriceBar],
    tqqq_prices: list[PriceBar],
    qld_prices: list[PriceBar],
    *,
    count: int = 100,
    min_days: int = 60,
    max_days: int | None = None,
    seed: int | None = None,
    uniform_start_sampling: bool = False,
    v4_split_count: int = 20,
    v4_compounding_type: str = "compound",
    v4_sell_percent: Decimal | None = None,
    v4_fill_model: str = "intraday_high",
    v4_initial_entry: str = "web_loc",
    v4_first_buy_buffer_percent: Decimal = Decimal("12"),
    data_diagnostics: dict | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Compare six fixed strategies over reproducible random common-date windows."""
    if count <= 0 or count > MAX_STRATEGY_RANDOM_SAMPLES:
        raise ValueError(f"6전략 랜덤 샘플 수는 1~{MAX_STRATEGY_RANDOM_SAMPLES:,}이어야 합니다.")
    if min_days < 2:
        raise ValueError("최소 거래일 수는 2 이상이어야 합니다.")

    comparison_kwargs = {
        "qld_prices": qld_prices,
        "tqqq_prices": tqqq_prices,
        "v4_split_count": v4_split_count,
        "v4_compounding_type": v4_compounding_type,
        "v4_sell_percent": v4_sell_percent,
        "v4_fill_model": v4_fill_model,
        "v4_initial_entry": v4_initial_entry,
        "v4_first_buy_buffer_percent": v4_first_buy_buffer_percent,
    }
    full_result = run_strategy_comparison(
        previous_config,
        soxx_prices,
        soxl_prices,
        result_type="strategy_random_reference",
        data_diagnostics=data_diagnostics,
        include_period_analysis=False,
        **comparison_kwargs,
    )
    common_dates = [item["date"] for item in full_result["comparison"]["equity_curve"]]
    if len(common_dates) < min_days:
        raise ValueError(
            f"요청한 최소 {min_days:,}거래일보다 6전략 공통 데이터 {len(common_dates):,}일이 짧습니다."
        )

    sampled_ranges: list[dict] = []
    if uniform_start_sampling:
        valid_start_count = len(common_dates) - min_days + 1
        effective_count = min(count, valid_start_count)
        for sample_index in range(effective_count):
            start_index = sample_index * valid_start_count // effective_count
            sampled_ranges.append({
                "sample": sample_index + 1,
                "start_date": common_dates[start_index],
                "end_date": common_dates[start_index + min_days - 1],
                "trading_days": min_days,
            })
    else:
        maximum = min(max_days or len(common_dates), len(common_dates))
        if maximum < min_days:
            raise ValueError(
                f"요청한 최소 {min_days:,}거래일보다 최대 거래일 {maximum:,}일이 짧습니다."
            )
        rng = random.Random(seed)
        effective_count = count
        for sample in range(1, effective_count + 1):
            length = rng.randint(min_days, maximum)
            start_index = rng.randint(0, len(common_dates) - length)
            sampled_ranges.append({
                "sample": sample,
                "start_date": common_dates[start_index],
                "end_date": common_dates[start_index + length - 1],
                "trading_days": length,
            })

    strategy_order = list(full_result["comparison"]["strategy_order"])
    if progress_callback:
        progress_callback(0, effective_count, {
            "phase": "sampling",
            "message": (
                f"유효 시작일 전체에 {effective_count:,}개 구간을 균등 배치했습니다."
                if uniform_start_sampling else f"공통 거래일에서 {effective_count:,}개 랜덤 구간을 준비했습니다."
            ),
        })
    rows: list[dict] = []
    return_win_shares = {key: ZERO for key in strategy_order}
    risk_win_shares = {key: ZERO for key in strategy_order}
    rank_totals = {key: ZERO for key in strategy_order}

    for completed, period in enumerate(sampled_ranges, start=1):
        start_date = period["start_date"]
        end_date = period["end_date"]
        result = run_strategy_comparison(
            previous_config,
            _filter(soxx_prices, start_date, end_date),
            _filter(soxl_prices, start_date, end_date),
            qld_prices=_filter(qld_prices, start_date, end_date),
            tqqq_prices=_filter(tqqq_prices, start_date, end_date),
            v4_split_count=v4_split_count,
            v4_compounding_type=v4_compounding_type,
            v4_sell_percent=v4_sell_percent,
            v4_fill_model=v4_fill_model,
            v4_initial_entry=v4_initial_entry,
            v4_first_buy_buffer_percent=v4_first_buy_buffer_percent,
            result_type="strategy_random_sample",
            include_period_analysis=False,
        )
        strategies: dict[str, dict] = {}
        for key in strategy_order:
            source = result["comparison"]["strategies"][key]
            strategies[key] = {
                "ending_equity": source["summary"]["ending_equity"],
                "return_rate": source["metrics"]["total_return"],
                "close_mdd": source["metrics"]["close_mdd"],
                "cagr": source["metrics"]["cagr"],
                "calmar_ratio": source["metrics"]["calmar_ratio"],
            }

        best_return = max(decimal(item["return_rate"]) for item in strategies.values())
        least_drawdown = max(decimal(item["close_mdd"]) for item in strategies.values())
        return_winners = [key for key in strategy_order if decimal(strategies[key]["return_rate"]) == best_return]
        risk_winners = [key for key in strategy_order if decimal(strategies[key]["close_mdd"]) == least_drawdown]
        for key in return_winners:
            return_win_shares[key] += Decimal("1") / Decimal(len(return_winners))
        for key in risk_winners:
            risk_win_shares[key] += Decimal("1") / Decimal(len(risk_winners))
        for key in strategy_order:
            value = decimal(strategies[key]["return_rate"])
            rank = 1 + sum(
                1 for other_key in strategy_order
                if decimal(strategies[other_key]["return_rate"]) > value
            )
            strategies[key]["return_rank"] = rank
            rank_totals[key] += Decimal(rank)

        rows.append({
            **period,
            "best_return_strategy": return_winners[0] if len(return_winners) == 1 else "tie",
            "best_return_rate": best_return,
            "lowest_mdd_strategy": risk_winners[0] if len(risk_winners) == 1 else "tie",
            "lowest_mdd": least_drawdown,
            "strategies": strategies,
        })
        if progress_callback:
            progress_callback(completed, effective_count, {
                "phase": "backtesting",
                "message": f"{completed:,}/{effective_count:,}번째 구간 계산 완료",
                "sample": period["sample"],
                "start_date": start_date,
                "end_date": end_date,
                "trading_days": period["trading_days"],
            })

    sample_count = Decimal(len(rows))
    if progress_callback:
        progress_callback(effective_count, effective_count, {
            "phase": "summarizing",
            "message": "6개 전략의 승률과 평균 성과를 요약하고 있습니다.",
        })
    summary: list[dict] = []
    for key in strategy_order:
        returns = [decimal(row["strategies"][key]["return_rate"]) for row in rows]
        mdds = [decimal(row["strategies"][key]["close_mdd"]) for row in rows]
        ending_equities = [decimal(row["strategies"][key]["ending_equity"]) for row in rows]
        calmars = [decimal(row["strategies"][key]["calmar_ratio"]) for row in rows]
        summary.append({
            "key": key,
            **STRATEGY_META[key],
            "sample_count": len(rows),
            "avg_return_rate": round_rate(_average(returns)),
            "median_return_rate": round_rate(decimal(statistics.median(returns))),
            "worst_return_rate": min(returns),
            "best_return_rate": max(returns),
            "positive_period_rate": round_rate(
                Decimal(sum(1 for value in returns if value > ZERO)) / sample_count * Decimal("100")
            ),
            "avg_ending_equity": round_money(_average(ending_equities)),
            "avg_close_mdd": round_rate(_average(mdds)),
            "worst_close_mdd": min(mdds),
            "avg_calmar_ratio": round_rate(_average(calmars)),
            "return_win_share": round_rate(return_win_shares[key]),
            "return_win_rate": round_rate(return_win_shares[key] / sample_count * Decimal("100")),
            "lowest_mdd_share": round_rate(risk_win_shares[key]),
            "lowest_mdd_rate": round_rate(risk_win_shares[key] / sample_count * Decimal("100")),
            "avg_return_rank": round_rate(rank_totals[key] / sample_count),
        })

    ordered_by_average = sorted(
        summary,
        key=lambda item: (-decimal(item["avg_return_rate"]), strategy_order.index(item["key"])),
    )
    for rank, item in enumerate(ordered_by_average, start=1):
        item["average_return_rank"] = rank

    warnings = list(full_result.get("warnings", []))
    if uniform_start_sampling and effective_count < count:
        warnings.append(
            f"균등 시작일 샘플은 {min_days:,}거래일 길이를 확보할 수 있는 "
            f"{effective_count:,}개 시작일까지만 적용했습니다. 요청값: {count:,}개."
        )

    return to_primitive({
        "result_type": "strategy_random_comparison",
        "strategy_order": strategy_order,
        "summary": ordered_by_average,
        "rows": rows,
        "period": {
            "start": common_dates[0],
            "end": common_dates[-1],
            "trading_days": len(common_dates),
        },
        "config": {
            "principal": previous_config.principal,
            "count": effective_count,
            "requested_count": count,
            "min_days": min_days,
            "max_days": max_days,
            "seed": seed,
            "uniform_start_sampling": uniform_start_sampling,
            "v4_split_count": v4_split_count,
            "v4_compounding_type": v4_compounding_type,
            "v4_sell_percent": v4_sell_percent,
            "v4_fill_model": v4_fill_model,
            "v4_initial_entry": v4_initial_entry,
            "v4_first_buy_buffer_percent": v4_first_buy_buffer_percent,
            "trigger_interval_pct": previous_config.trigger_interval_pct,
            "divisions": previous_config.divisions,
            "fractional_shares": previous_config.fractional_shares,
            "liquidation_offset_pct": previous_config.liquidation_offset_pct,
            "slippage_bps": previous_config.slippage_bps,
            "commission": previous_config.commission,
            "sell_fee_bps": previous_config.sell_fee_bps,
        },
        "alignment": full_result["comparison"]["alignment"],
        "warnings": warnings,
        "methodology": {
            "range_sampling": (
                "evenly_spaced_valid_start_dates_with_fixed_minimum_length"
                if uniform_start_sampling else "seeded_uniform_length_and_start_on_strict_common_trading_dates"
            ),
            "requested_sample_count": count,
            "effective_sample_count": effective_count,
            "sample_count_capped": effective_count < count,
            "fixed_trading_days": min_days if uniform_start_sampling else None,
            "seed_ignored": uniform_start_sampling,
            "same_period_for_all_strategies": True,
            "strategy_parameters_fixed_from_control_panel": True,
            "return_wins_split_equally_on_ties": True,
            "mdd_basis": "daily_close_equity",
        },
    })
