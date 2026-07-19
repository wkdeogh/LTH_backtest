from __future__ import annotations

import random
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .data import default_csv_path, load_prices
from .engine import run_backtest
from .models import BacktestConfig, PriceBar
from .precision import ONE, ZERO, decimal, round_money, round_rate, to_primitive


def _hold(principal: Decimal, bars: list[PriceBar]) -> tuple[Decimal, Decimal]:
    ending = round_money(principal * bars[-1].close / bars[0].close)
    rate = round_rate(((ending / principal) - ONE) * Decimal("100"))
    return ending, rate


def _rank_sample_rows(rows: list[dict]) -> None:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[int(row["sample"])].append(row)

    for group in grouped.values():
        best_return = max(decimal(row["strategy_profit_rate"]) for row in group)
        best_mdd = max(decimal(row["close_mdd"]) for row in group)
        return_winners = sum(1 for row in group if decimal(row["strategy_profit_rate"]) == best_return)
        mdd_winners = sum(1 for row in group if decimal(row["close_mdd"]) == best_mdd)
        for row in group:
            strategy_return = decimal(row["strategy_profit_rate"])
            close_mdd = decimal(row["close_mdd"])
            row["return_rank"] = 1 + sum(
                1 for other in group if decimal(other["strategy_profit_rate"]) > strategy_return
            )
            row["mdd_rank"] = 1 + sum(
                1 for other in group if decimal(other["close_mdd"]) > close_mdd
            )
            row["return_win_share"] = ONE / Decimal(return_winners) if strategy_return == best_return else ZERO
            row["lowest_mdd_share"] = ONE / Decimal(mdd_winners) if close_mdd == best_mdd else ZERO


def run_random_comparison(
    *,
    symbols: list[str],
    splits: list[int],
    principal: Decimal,
    start_date: str,
    end_date: str,
    count: int = 100,
    min_days: int = 60,
    max_days: int | None = None,
    seed: int | None = None,
    uniform_start_sampling: bool = False,
    csv_dir: Path | None = None,
    compounding_type: str = "compound",
    sell_percent: Decimal | None = None,
    fill_model: str = "intraday_high",
    slippage_bps: Decimal = ZERO,
    commission: Decimal = ZERO,
    sell_fee_bps: Decimal = ZERO,
    progress_callback: Callable[[int, int, dict], None] | None = None,
) -> dict:
    if count <= 0:
        raise ValueError("랜덤 샘플 수는 1 이상이어야 합니다.")
    if min_days < 2:
        raise ValueError("최소 거래일 수는 2 이상이어야 합니다.")
    principal = decimal(principal)
    symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
    splits = list(dict.fromkeys(int(split) for split in splits))
    if not symbols or not splits:
        raise ValueError("랜덤 비교에는 종목과 분할 수가 각각 하나 이상 필요합니다.")
    csv_dir = csv_dir.resolve() if csv_dir else None

    def path_for(symbol: str) -> Path:
        return csv_dir / f"{symbol}.csv" if csv_dir else default_csv_path(symbol)

    benchmark, _ = load_prices(path_for("QLD"), start_date, end_date)
    symbol_bars: dict[str, list[PriceBar]] = {}
    common_date_set = {bar.date for bar in benchmark}
    for symbol in symbols:
        bars, _ = load_prices(path_for(symbol), start_date, end_date)
        symbol_bars[symbol] = bars
        common_date_set.intersection_update(bar.date for bar in bars)
    common_dates = sorted(common_date_set)
    if len(common_dates) < min_days:
        raise ValueError(
            f"요청한 최소 {min_days:,}거래일보다 선택 종목·QLD 공통 데이터 {len(common_dates):,}일이 짧습니다."
        )

    qld_by_date = {bar.date: bar for bar in benchmark}
    symbol_by_date = {
        symbol: {bar.date: bar for bar in bars}
        for symbol, bars in symbol_bars.items()
    }
    ranges: list[dict] = []
    if uniform_start_sampling:
        valid_start_count = len(common_dates) - min_days + 1
        effective_count = min(count, valid_start_count)
        sampled_indexes = [
            (sample_index * valid_start_count // effective_count, min_days)
            for sample_index in range(effective_count)
        ]
    else:
        maximum = min(max_days or len(common_dates), len(common_dates))
        if maximum < min_days:
            raise ValueError(
                f"요청한 최소 {min_days:,}거래일보다 최대 거래일 {maximum:,}일이 짧습니다."
            )
        rng = random.Random(seed)
        effective_count = count
        sampled_indexes = []
        for _ in range(effective_count):
            length = rng.randint(min_days, maximum)
            sampled_indexes.append((rng.randint(0, len(common_dates) - length), length))

    for sample, (start_index, length) in enumerate(sampled_indexes, start=1):
        dates = common_dates[start_index:start_index + length]
        qld_bars = [qld_by_date[date] for date in dates]
        ending, rate = _hold(principal, qld_bars)
        ranges.append({
            "sample": sample,
            "start_date": dates[0],
            "end_date": dates[-1],
            "trading_days": len(dates),
            "dates": dates,
            "qld_ending_equity": ending,
            "qld_profit_rate": rate,
        })

    rows: list[dict] = []
    warnings: list[str] = []
    combination_order = [f"{symbol.lower()}_{split}" for symbol in symbols for split in splits]
    total_runs = len(combination_order) * len(ranges)
    completed_runs = 0
    if progress_callback:
        progress_callback(0, total_runs, {
            "phase": "sampling",
            "message": (
                f"공통 거래일의 유효 시작일 전체에 {len(ranges):,}개 고정 구간을 균등 배치했습니다."
                if uniform_start_sampling else f"{len(ranges):,}개 구간 × {len(combination_order):,}개 조합을 준비했습니다."
            ),
        })
    for symbol in symbols:
        for split in splits:
            key = f"{symbol.lower()}_{split}"
            for period in ranges:
                bars = [symbol_by_date[symbol][date] for date in period["dates"]]
                config = BacktestConfig(
                    symbol=symbol,
                    split_count=split,
                    principal=principal,
                    compounding_type=compounding_type,
                    sell_percent=sell_percent,
                    fill_model=fill_model,
                    slippage_bps=slippage_bps,
                    commission=commission,
                    sell_fee_bps=sell_fee_bps,
                )
                result = run_backtest(config, bars)
                hold_ending, hold_rate = _hold(principal, bars)
                strategy_rate = decimal(result.summary["profit_rate"])
                rows.append({
                    "key": key,
                    "label": f"{symbol} · {split}분할",
                    "symbol": symbol,
                    "split_count": split,
                    "sample": period["sample"],
                    "start_date": bars[0].date,
                    "end_date": bars[-1].date,
                    "trading_days": len(bars),
                    "strategy_ending_equity": result.summary["ending_equity"],
                    "strategy_profit_rate": strategy_rate,
                    "hold_ending_equity": hold_ending,
                    "hold_profit_rate": hold_rate,
                    "strategy_minus_hold": round_rate(strategy_rate - hold_rate),
                    "qld_ending_equity": period["qld_ending_equity"],
                    "qld_profit_rate": period["qld_profit_rate"],
                    "strategy_minus_qld": round_rate(strategy_rate - decimal(period["qld_profit_rate"])),
                    "close_mdd": result.metrics.get("close_mdd", ZERO),
                    "completed_rounds": len(result.rounds),
                    "execution_count": len(result.executions),
                    "intraday_high_only_fills": result.diagnostics.get("intraday_high_only_fills", 0),
                })
                completed_runs += 1
                if progress_callback:
                    progress_callback(completed_runs, total_runs, {
                        "phase": "backtesting",
                        "message": f"{completed_runs:,}/{total_runs:,}개 조합 계산 완료",
                        "symbol": symbol,
                        "split_count": split,
                        "sample": period["sample"],
                    })

    _rank_sample_rows(rows)
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    if progress_callback:
        progress_callback(total_runs, total_runs, {
            "phase": "summarizing",
            "message": "종목·분할 조합별 평균 성과를 요약하고 있습니다.",
        })
    for row in rows:
        grouped[(row["symbol"], row["split_count"])].append(row)
    summary: list[dict] = []
    for symbol in symbols:
        for split in splits:
            group = grouped[(symbol, split)]
            key = f"{symbol.lower()}_{split}"
            size = Decimal(len(group))
            strategy_average = sum((decimal(row["strategy_profit_rate"]) for row in group), ZERO) / size
            hold_average = sum((decimal(row["hold_profit_rate"]) for row in group), ZERO) / size
            qld_average = sum((decimal(row["qld_profit_rate"]) for row in group), ZERO) / size
            average_mdd = sum((decimal(row["close_mdd"]) for row in group), ZERO) / size
            summary.append({
                "key": key,
                "label": f"{symbol} · {split}분할",
                "symbol": symbol,
                "split_count": split,
                "sample_count": len(group),
                "avg_strategy_profit_rate": round_rate(strategy_average),
                "avg_return_rate": round_rate(strategy_average),
                "median_strategy_profit_rate": round_rate(statistics.median(decimal(row["strategy_profit_rate"]) for row in group)),
                "avg_strategy_ending_equity": round_money(sum((decimal(row["strategy_ending_equity"]) for row in group), ZERO) / size),
                "avg_ending_equity": round_money(sum((decimal(row["strategy_ending_equity"]) for row in group), ZERO) / size),
                "avg_hold_profit_rate": round_rate(hold_average),
                "avg_qld_profit_rate": round_rate(qld_average),
                "avg_excess_vs_hold": round_rate(strategy_average - hold_average),
                "avg_excess_vs_qld": round_rate(strategy_average - qld_average),
                "strategy_win_count": sum(1 for row in group if decimal(row["strategy_minus_hold"]) > ZERO),
                "strategy_win_rate": round_rate(Decimal(sum(1 for row in group if decimal(row["strategy_minus_hold"]) > ZERO)) / size * Decimal("100")),
                "return_win_rate": round_rate(sum((decimal(row["return_win_share"]) for row in group), ZERO) / size * Decimal("100")),
                "lowest_mdd_rate": round_rate(sum((decimal(row["lowest_mdd_share"]) for row in group), ZERO) / size * Decimal("100")),
                "avg_return_rank": round_rate(sum((Decimal(row["return_rank"]) for row in group), ZERO) / size),
                "positive_period_rate": round_rate(Decimal(sum(1 for row in group if decimal(row["strategy_profit_rate"]) > ZERO)) / size * Decimal("100")),
                "avg_close_mdd": round_rate(average_mdd),
                "worst_return": min(decimal(row["strategy_profit_rate"]) for row in group),
                "worst_return_rate": min(decimal(row["strategy_profit_rate"]) for row in group),
                "best_return": max(decimal(row["strategy_profit_rate"]) for row in group),
                "best_return_rate": max(decimal(row["strategy_profit_rate"]) for row in group),
                "worst_close_mdd": min(decimal(row["close_mdd"]) for row in group),
                "intraday_high_only_fills": sum(int(row["intraday_high_only_fills"]) for row in group),
            })

    for item in summary:
        average_return = decimal(item["avg_return_rate"])
        item["average_return_rank"] = 1 + sum(
            1 for other in summary if decimal(other["avg_return_rate"]) > average_return
        )

    sample_groups: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        sample_groups[int(row["sample"])].append(row)
    sample_rows = []
    for period in ranges:
        group = {row["key"]: row for row in sample_groups[period["sample"]]}
        sample_rows.append({
            "sample": period["sample"],
            "start_date": period["start_date"],
            "end_date": period["end_date"],
            "trading_days": period["trading_days"],
            "strategies": {
                key: {
                    "return_rate": group[key]["strategy_profit_rate"],
                    "ending_equity": group[key]["strategy_ending_equity"],
                    "close_mdd": group[key]["close_mdd"],
                    "return_rank": group[key]["return_rank"],
                    "mdd_rank": group[key]["mdd_rank"],
                }
                for key in combination_order
            },
        })

    if uniform_start_sampling and effective_count < count:
        warnings.append(
            f"균등 시작일 샘플은 {min_days:,}거래일 길이를 확보할 수 있는 "
            f"{effective_count:,}개 시작일까지만 적용했습니다. 요청값: {count:,}개."
        )

    return to_primitive({
        "result_type": "lth_random_comparison",
        "combination_order": combination_order,
        "period": {
            "start": common_dates[0],
            "end": common_dates[-1],
            "trading_days": len(common_dates),
        },
        "config": {
            "symbols": symbols,
            "splits": splits,
            "principal": principal,
            "start_date": start_date,
            "end_date": end_date,
            "count": effective_count,
            "requested_count": count,
            "min_days": min_days,
            "max_days": max_days,
            "seed": seed,
            "uniform_start_sampling": uniform_start_sampling,
            "compounding_type": compounding_type,
            "sell_percent": sell_percent,
            "fill_model": fill_model,
        },
        "summary": summary,
        "rows": rows,
        "sample_rows": sample_rows,
        "warnings": list(dict.fromkeys(warnings)),
        "methodology": {
            "range_sampling": (
                "evenly_spaced_valid_start_dates_with_fixed_minimum_length"
                if uniform_start_sampling else "seeded_uniform_length_and_start_on_strict_common_trading_dates"
            ),
            "strict_common_dates": True,
            "requested_sample_count": count,
            "effective_sample_count": effective_count,
            "sample_count_capped": effective_count < count,
            "fixed_trading_days": min_days if uniform_start_sampling else None,
            "seed_ignored": uniform_start_sampling,
            "same_period_for_all_combinations": True,
            "return_wins_split_equally_on_ties": True,
            "lowest_mdd_wins_split_equally_on_ties": True,
        },
    })
