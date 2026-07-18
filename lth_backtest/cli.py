from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from .data import DATA_ROOT, download_prices, load_prices, parse_date, resolve_csv_path
from .engine import run_backtest
from .models import BacktestConfig
from .precision import decimal, to_primitive
from .random_compare import run_random_comparison
from .reporting import write_html_report, write_json, write_random_html_report, write_result_csvs


def _config(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        symbol=args.symbol,
        split_count=args.split_count,
        principal=decimal(args.principal),
        compounding_type="simple" if args.simple else "compound",
        sell_percent=decimal(args.sell_percent) if args.sell_percent is not None else None,
        fill_model=args.fill_model,
        initial_entry=args.initial_entry,
        first_buy_buffer_percent=decimal(args.first_buy_buffer),
        slippage_bps=decimal(args.slippage_bps),
        commission=decimal(args.commission),
        sell_fee_bps=decimal(args.sell_fee_bps),
        annual_risk_free_rate=decimal(args.risk_free_rate),
    )


def _print_result(result: object) -> None:
    data = to_primitive(result)
    summary = data["summary"]
    metrics = data["metrics"]
    config = data["config"]
    period = data["period"]
    print("\nBackTest version2 결과")
    print("======================")
    print(f"{config['symbol']} · {config['split_count']}분할 · {config['compounding_type']} · {config['fill_model']}")
    print(f"기간: {period['start']} ~ {period['end']} ({period['trading_days']:,}거래일)")
    print(f"최종 자산: ${summary['ending_equity']:,.2f}")
    print(f"손익: ${summary['profit_amount']:,.2f} ({summary['profit_rate']:+,.2f}%)")
    print(f"거치식: {summary['benchmark_profit_rate']:+,.2f}% · 초과수익: {summary['excess_return_rate']:+,.2f}%p")
    if summary.get("qld_benchmark_profit_rate") is not None:
        print(f"QLD 거치식: {summary['qld_benchmark_profit_rate']:+,.2f}%")
    print(f"CAGR: {metrics.get('cagr', 0):,.2f}% · 종가 MDD: {metrics.get('close_mdd', 0):,.2f}% · Sharpe: {metrics.get('sharpe_ratio', 0):,.3f}")
    print(f"완료 라운드: {summary['completed_rounds']:,} · 체결: {summary['execution_count']:,} · 보유: {summary['open_position_qty']:,}주")
    print(f"장중 고가만으로 체결된 최종 지정가 매도: {data['diagnostics'].get('intraday_high_only_fills', 0):,}건")
    for warning in data.get("warnings", []):
        print(f"주의: {warning}")


def _save_outputs(result: object, args: argparse.Namespace) -> None:
    if getattr(args, "json_out", None):
        print(f"JSON 저장: {write_json(result, Path(args.json_out))}")
    if getattr(args, "html_out", None):
        print(f"HTML 저장: {write_html_report(result, Path(args.html_out))}")
    if getattr(args, "csv_out_dir", None):
        paths = write_result_csvs(result, Path(args.csv_out_dir))
        print(f"CSV 저장: {', '.join(str(path) for path in paths)}")


def command_run(args: argparse.Namespace) -> object:
    path = resolve_csv_path(args.csv, args.symbol)
    bars, diagnostics = load_prices(path, args.start_date, args.end_date)
    qld_bars = None
    if not args.no_qld:
        qld_path = resolve_csv_path(args.qld_csv, "QLD")
        if qld_path.exists():
            qld_bars, _ = load_prices(qld_path, args.start_date, args.end_date)
    result = run_backtest(_config(args), bars, diagnostics, qld_bars)
    _print_result(result)
    _save_outputs(result, args)
    return result


def command_download(args: argparse.Namespace) -> None:
    target = Path(args.out).resolve() if args.out else DATA_ROOT / f"{args.symbol.upper()}.csv"
    print(f"저장: {download_prices(args.symbol, args.start_date, args.end_date, target)}")


def command_all(args: argparse.Namespace) -> object:
    target = resolve_csv_path(args.csv, args.symbol) if args.csv else DATA_ROOT / f"{args.symbol.upper()}.csv"
    download_prices(args.symbol, args.start_date, args.end_date, target)
    args.csv = str(target)
    if not args.no_qld:
        qld_target = resolve_csv_path(args.qld_csv, "QLD") if args.qld_csv else DATA_ROOT / "QLD.csv"
        download_prices("QLD", args.start_date, args.end_date, qld_target)
        args.qld_csv = str(qld_target)
    return command_run(args)


def command_random(args: argparse.Namespace) -> object:
    result = run_random_comparison(
        symbols=args.symbols,
        splits=args.splits,
        principal=decimal(args.principal),
        start_date=args.start_date,
        end_date=args.end_date,
        count=args.count,
        min_days=args.min_days,
        max_days=args.max_days,
        seed=args.seed,
        csv_dir=Path(args.csv_dir) if args.csv_dir else None,
        compounding_type="simple" if args.simple else "compound",
        sell_percent=decimal(args.sell_percent) if args.sell_percent is not None else None,
        fill_model=args.fill_model,
        slippage_bps=decimal(args.slippage_bps),
        commission=decimal(args.commission),
        sell_fee_bps=decimal(args.sell_fee_bps),
    )
    print("\n랜덤 기간 비교")
    for item in result["summary"]:
        print(
            f"{item['symbol']} {item['split_count']}분할 · 평균 {item['avg_strategy_profit_rate']:+.2f}% · "
            f"거치식 대비 {item['avg_excess_vs_hold']:+.2f}%p · 승률 {item['strategy_win_rate']:.1f}%"
        )
    if args.json_out:
        write_json(result, Path(args.json_out))
        print(f"JSON 저장: {args.json_out}")
    if args.html_out:
        write_random_html_report(result, Path(args.html_out))
        print(f"HTML 저장: {args.html_out}")
    return result


def command_serve(args: argparse.Namespace) -> None:
    from .web import serve
    serve(args.host, args.port, args.open)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="무한매수법 V4 정밀 백테스터 version2")
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser("download", help="Yahoo Finance 조정 OHLCV 다운로드")
    download.add_argument("symbol", choices=["TQQQ", "SOXL", "QLD"])
    download.add_argument("start_date", type=lambda value: parse_date(value, "시작일"))
    download.add_argument("end_date", type=lambda value: parse_date(value, "종료일"))
    download.add_argument("--out")
    download.set_defaults(func=command_download)

    def add_run(target: argparse.ArgumentParser) -> None:
        target.add_argument("symbol", choices=["TQQQ", "SOXL"])
        target.add_argument("split_count", type=int, choices=[20, 30, 40])
        target.add_argument("principal", type=Decimal)
        target.add_argument("start_date", type=lambda value: parse_date(value, "시작일"))
        target.add_argument("end_date", type=lambda value: parse_date(value, "종료일"))
        target.add_argument("--csv")
        target.add_argument("--qld-csv", help="QLD 비교 CSV 경로")
        target.add_argument("--no-qld", action="store_true", help="QLD 거치식 비교 생략")
        target.add_argument("--simple", action="store_true")
        target.add_argument("--sell-percent", type=Decimal)
        target.add_argument("--fill-model", choices=["intraday_high", "close_only"], default="intraday_high")
        target.add_argument("--initial-entry", choices=["moc", "web_loc"], default="web_loc")
        target.add_argument("--first-buy-buffer", type=Decimal, default=Decimal("12"))
        target.add_argument("--slippage-bps", type=Decimal, default=Decimal("0"))
        target.add_argument("--commission", type=Decimal, default=Decimal("0"))
        target.add_argument("--sell-fee-bps", type=Decimal, default=Decimal("0"))
        target.add_argument("--risk-free-rate", type=Decimal, default=Decimal("0"))
        target.add_argument("--json-out")
        target.add_argument("--html-out")
        target.add_argument("--csv-out-dir")

    run = sub.add_parser("run", help="CSV로 단일 백테스트")
    add_run(run)
    run.set_defaults(func=command_run)
    all_command = sub.add_parser("all", help="가격 다운로드 후 단일 백테스트")
    add_run(all_command)
    all_command.set_defaults(func=command_all)

    random_parser = sub.add_parser("random", aliases=["rand"], help="랜덤 기간 전략/거치식/QLD 비교")
    random_parser.add_argument("--symbols", nargs="+", choices=["TQQQ", "SOXL"], default=["TQQQ", "SOXL"])
    random_parser.add_argument("--splits", nargs="+", type=int, choices=[20, 30, 40], default=[20, 40])
    random_parser.add_argument("--principal", type=Decimal, default=Decimal("20000"))
    random_parser.add_argument("--start-date", default="2020-01-01", type=lambda value: parse_date(value, "시작일"))
    random_parser.add_argument("--end-date", default=date.today().isoformat(), type=lambda value: parse_date(value, "종료일"))
    random_parser.add_argument("--count", "-n", type=int, default=100)
    random_parser.add_argument("--min-days", type=int, default=60)
    random_parser.add_argument("--max-days", type=int)
    random_parser.add_argument("--seed", type=int)
    random_parser.add_argument("--csv-dir")
    random_parser.add_argument("--simple", action="store_true")
    random_parser.add_argument("--sell-percent", type=Decimal)
    random_parser.add_argument("--fill-model", choices=["intraday_high", "close_only"], default="intraday_high")
    random_parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("0"))
    random_parser.add_argument("--commission", type=Decimal, default=Decimal("0"))
    random_parser.add_argument("--sell-fee-bps", type=Decimal, default=Decimal("0"))
    random_parser.add_argument("--json-out")
    random_parser.add_argument("--html-out")
    random_parser.set_defaults(func=command_random)

    server = sub.add_parser("serve", help="브라우저 UI 실행")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--open", action="store_true")
    server.set_defaults(func=command_serve)
    return parser


def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        print("\n브라우저 UI: python3 -m lth_backtest.cli serve --open")
        return
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
