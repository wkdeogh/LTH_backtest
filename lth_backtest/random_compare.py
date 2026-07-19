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


def _filter(bars: list[PriceBar], start: str, end: str) -> list[PriceBar]:
    return [bar for bar in bars if start <= bar.date <= end]


def _hold(principal: Decimal, bars: list[PriceBar]) -> tuple[Decimal, Decimal]:
    ending = round_money(principal * bars[-1].close / bars[0].close)
    rate = round_rate(((ending / principal) - ONE) * Decimal("100"))
    return ending, rate


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
    symbols = [symbol.upper() for symbol in symbols]
    csv_dir = csv_dir.resolve() if csv_dir else None

    def path_for(symbol: str) -> Path:
        return csv_dir / f"{symbol}.csv" if csv_dir else default_csv_path(symbol)

    benchmark, _ = load_prices(path_for("QLD"), start_date, end_date)
    maximum = min(max_days or len(benchmark), len(benchmark))
    if maximum < min_days:
        raise ValueError("요청한 랜덤 기간보다 QLD 가격 데이터가 짧습니다.")
    rng = random.Random(seed)
    ranges: list[dict] = []
    for sample in range(1, count + 1):
        length = rng.randint(min_days, maximum)
        start_index = rng.randint(0, len(benchmark) - length)
        sample_bars = benchmark[start_index:start_index + length]
        ending, rate = _hold(principal, sample_bars)
        ranges.append({
            "sample": sample,
            "start_date": sample_bars[0].date,
            "end_date": sample_bars[-1].date,
            "trading_days": len(sample_bars),
            "qld_ending_equity": ending,
            "qld_profit_rate": rate,
        })

    rows: list[dict] = []
    warnings: list[str] = []
    total_runs = len(symbols) * len(splits) * len(ranges)
    completed_runs = 0
    if progress_callback:
        progress_callback(0, total_runs, {
            "phase": "sampling",
            "message": f"{len(ranges):,}개 구간 × {len(symbols) * len(splits):,}개 조합을 준비했습니다.",
        })
    for symbol in symbols:
        symbol_bars, _ = load_prices(path_for(symbol), start_date, end_date)
        for split in splits:
            for period in ranges:
                bars = _filter(symbol_bars, period["start_date"], period["end_date"])
                if len(bars) < 2:
                    warnings.append(f"{symbol} {period['start_date']}~{period['end_date']}: 데이터 부족으로 제외")
                    completed_runs += 1
                    if progress_callback:
                        progress_callback(completed_runs, total_runs, {
                            "phase": "backtesting",
                            "message": f"{completed_runs:,}/{total_runs:,}개 조합 계산 완료",
                            "symbol": symbol,
                            "split_count": split,
                            "sample": period["sample"],
                        })
                    continue
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

    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    if progress_callback:
        progress_callback(total_runs, total_runs, {
            "phase": "summarizing",
            "message": "종목·분할 조합별 평균 성과를 요약하고 있습니다.",
        })
    for row in rows:
        grouped[(row["symbol"], row["split_count"])].append(row)
    summary: list[dict] = []
    for (symbol, split), group in sorted(grouped.items()):
        size = Decimal(len(group))
        strategy_average = sum((decimal(row["strategy_profit_rate"]) for row in group), ZERO) / size
        hold_average = sum((decimal(row["hold_profit_rate"]) for row in group), ZERO) / size
        qld_average = sum((decimal(row["qld_profit_rate"]) for row in group), ZERO) / size
        summary.append({
            "symbol": symbol,
            "split_count": split,
            "sample_count": len(group),
            "avg_strategy_profit_rate": round_rate(strategy_average),
            "median_strategy_profit_rate": statistics.median(decimal(row["strategy_profit_rate"]) for row in group),
            "avg_hold_profit_rate": round_rate(hold_average),
            "avg_qld_profit_rate": round_rate(qld_average),
            "avg_excess_vs_hold": round_rate(strategy_average - hold_average),
            "avg_excess_vs_qld": round_rate(strategy_average - qld_average),
            "strategy_win_count": sum(1 for row in group if decimal(row["strategy_minus_hold"]) > ZERO),
            "strategy_win_rate": round_rate(Decimal(sum(1 for row in group if decimal(row["strategy_minus_hold"]) > ZERO)) / size * Decimal("100")),
            "worst_return": min(decimal(row["strategy_profit_rate"]) for row in group),
            "best_return": max(decimal(row["strategy_profit_rate"]) for row in group),
            "worst_close_mdd": min(decimal(row["close_mdd"]) for row in group),
            "intraday_high_only_fills": sum(int(row["intraday_high_only_fills"]) for row in group),
        })

    return to_primitive({
        "config": {
            "symbols": symbols,
            "splits": splits,
            "principal": principal,
            "start_date": start_date,
            "end_date": end_date,
            "count": count,
            "min_days": min_days,
            "max_days": max_days,
            "seed": seed,
            "compounding_type": compounding_type,
            "sell_percent": sell_percent,
            "fill_model": fill_model,
        },
        "summary": summary,
        "rows": rows,
        "warnings": list(dict.fromkeys(warnings)),
    })
