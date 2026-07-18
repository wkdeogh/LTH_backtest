from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import PriceBar
from .precision import ZERO, decimal, round_market_price


PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DATA_ROOT = REPOSITORY_ROOT / "data"
VALID_PRICE_SYMBOLS = {"TQQQ", "SOXL", "QLD"}
FULL_HISTORY_START_DATE = "1970-01-02"
DOWNLOAD_SYMBOLS = ("TQQQ", "SOXL", "QLD")
PRICE_BASIS_ACTUAL = "actual_split_adjusted"


def parse_date(value: str, label: str = "날짜") -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{label}는 YYYY-MM-DD 형식이어야 합니다.") from error
    return value


def default_csv_path(symbol: str, prefer_existing: bool = True) -> Path:
    symbol = symbol.upper()
    return DATA_ROOT / f"{symbol}.csv"


def resolve_csv_path(path_value: str | Path | None, symbol: str) -> Path:
    if path_value in (None, ""):
        return default_csv_path(symbol)
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (REPOSITORY_ROOT / path).resolve()
    if path.suffix.lower() != ".csv":
        raise ValueError("가격 데이터 파일은 .csv여야 합니다.")
    return path


def load_prices(csv_path: Path, start_date: str, end_date: str) -> tuple[list[PriceBar], dict]:
    parse_date(start_date, "시작일")
    parse_date(end_date, "종료일")
    if start_date > end_date:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    if not csv_path.exists():
        raise FileNotFoundError(f"가격 CSV를 찾을 수 없습니다: {csv_path}")

    bars: list[PriceBar] = []
    seen: set[str] = set()
    adjusted_rows = 0
    price_bases: set[str] = set()
    with csv_path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"date", "open", "high", "low", "close"}
        headers = {header.strip().lower() for header in (reader.fieldnames or [])}
        if not required.issubset(headers):
            missing = ", ".join(sorted(required - headers))
            raise ValueError(f"CSV 필수 열이 없습니다: {missing}")

        for raw_row in reader:
            row = {(key or "").strip().lower(): value for key, value in raw_row.items()}
            date_value = (row.get("date") or "").strip()
            if not date_value or date_value < start_date or date_value > end_date:
                continue
            parse_date(date_value, "CSV 날짜")
            if date_value in seen:
                raise ValueError(f"중복 거래일이 있습니다: {date_value}")
            seen.add(date_value)
            try:
                open_price = round_market_price(decimal(row.get("open")))
                high_price = round_market_price(decimal(row.get("high")))
                low_price = round_market_price(decimal(row.get("low")))
                close_price = round_market_price(decimal(row.get("close")))
                adj_close = round_market_price(decimal(row.get("adj_close") or row.get("adj close") or close_price))
                volume = int(decimal(row.get("volume") or 0))
            except Exception as error:
                raise ValueError(f"{date_value} 행에 숫자가 아닌 값이 있습니다.") from error

            if min(open_price, high_price, low_price, close_price, adj_close) <= ZERO:
                raise ValueError(f"{date_value} 행의 가격은 모두 0보다 커야 합니다.")
            if high_price < max(open_price, close_price, low_price):
                raise ValueError(f"{date_value} 행의 고가가 시가/저가/종가보다 작습니다.")
            if low_price > min(open_price, close_price, high_price):
                raise ValueError(f"{date_value} 행의 저가가 시가/고가/종가보다 큽니다.")
            price_basis = (row.get("price_basis") or "").strip().lower()
            if price_basis:
                price_bases.add(price_basis)
            if adj_close != close_price:
                adjusted_rows += 1
            bars.append(PriceBar(date_value, open_price, high_price, low_price, close_price, adj_close, volume))

    bars.sort(key=lambda item: item.date)
    if len(bars) < 2:
        raise ValueError("백테스트에는 최소 2거래일의 가격 데이터가 필요합니다.")
    if len(price_bases) > 1:
        raise ValueError("CSV에 서로 다른 가격 기준이 섞여 있습니다.")
    is_managed_dataset = csv_path.resolve().parent == DATA_ROOT.resolve()
    price_basis = next(iter(price_bases), "user_provided")
    if is_managed_dataset and price_basis != PRICE_BASIS_ACTUAL:
        raise ValueError("기존 배당 조정 데이터입니다. 왼쪽 패널 맨 아래에서 전체 데이터를 갱신한 뒤 다시 실행하세요.")

    gap_count = 0
    max_gap_days = 0
    for previous, current in zip(bars, bars[1:]):
        gap = (datetime.strptime(current.date, "%Y-%m-%d") - datetime.strptime(previous.date, "%Y-%m-%d")).days
        max_gap_days = max(max_gap_days, gap)
        if gap > 5:
            gap_count += 1

    diagnostics = {
        "csv_path": str(csv_path),
        "row_count": len(bars),
        "first_date": bars[0].date,
        "last_date": bars[-1].date,
        "adjusted_close_diff_rows": adjusted_rows,
        "auto_adjusted_ohlc_rows": 0,
        "price_basis": price_basis,
        "dividend_adjustment": "not_applied_to_ohlc",
        "split_adjustment": "included_in_yahoo_quote_ohlc",
        "long_gap_count": gap_count,
        "max_calendar_gap_days": max_gap_days,
        "has_ohlc": True,
        "high_validation": "passed",
    }
    return bars, diagnostics


def _unix_seconds(date_value: str) -> int:
    date = datetime.strptime(date_value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(date.timestamp())


def download_prices(symbol: str, start_date: str, end_date: str, out_path: Path | None = None) -> Path:
    symbol = symbol.upper()
    if symbol not in VALID_PRICE_SYMBOLS:
        raise ValueError("가격 다운로드는 TQQQ, SOXL, QLD를 지원합니다.")
    parse_date(start_date, "시작일")
    parse_date(end_date, "종료일")
    if start_date > end_date:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    end_plus_one = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    params = urlencode({
        "period1": _unix_seconds(start_date),
        "period2": _unix_seconds(end_plus_one),
        "interval": "1d",
        "events": "history|split|div",
    })
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (BackTest version2)"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    if chart.get("error"):
        error = chart["error"]
        raise RuntimeError(error.get("description") or error.get("code") or "가격 다운로드 실패")
    result = (chart.get("result") or [None])[0]
    if not result or not result.get("timestamp"):
        raise RuntimeError("다운로드된 가격 데이터가 없습니다.")
    quote = (result.get("indicators", {}).get("quote") or [None])[0]
    adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose", [])
    if not quote:
        raise RuntimeError("OHLC 데이터가 없습니다.")

    rows: list[dict] = []
    for index, timestamp in enumerate(result["timestamp"]):
        try:
            close_raw = quote.get("close", [])[index]
            adj_raw = adjusted[index] if index < len(adjusted) else close_raw
        except IndexError:
            continue
        if close_raw is None or adj_raw is None or close_raw <= 0 or adj_raw <= 0:
            continue
        values: dict[str, Decimal] = {}
        valid = True
        for name in ("open", "high", "low", "close"):
            raw_values = quote.get(name, [])
            raw = raw_values[index] if index < len(raw_values) else None
            if raw is None or raw <= 0:
                valid = False
                break
            values[name] = round_market_price(decimal(raw))
        if not valid:
            continue
        rows.append({
            "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": values["open"],
            "high": values["high"],
            "low": values["low"],
            "close": values["close"],
            "adj_close": round_market_price(decimal(adj_raw)),
            "volume": int((quote.get("volume", [0])[index] if index < len(quote.get("volume", [])) else 0) or 0),
            "price_basis": PRICE_BASIS_ACTUAL,
        })
    if not rows:
        raise RuntimeError("유효한 가격 행이 없습니다.")

    target = out_path or (DATA_ROOT / f"{symbol}.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["date", "open", "high", "low", "close", "adj_close", "volume", "price_basis"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()})
    return target


def download_all_prices(end_date: str | None = None, out_dir: Path | None = None) -> list[Path]:
    """Download complete available histories for every strategy and benchmark symbol."""
    resolved_end_date = parse_date(end_date or date.today().isoformat(), "종료일")
    target_dir = out_dir or DATA_ROOT
    target_dir.mkdir(parents=True, exist_ok=True)
    return [
        download_prices(
            symbol,
            FULL_HISTORY_START_DATE,
            resolved_end_date,
            target_dir / f"{symbol}.csv",
        )
        for symbol in DOWNLOAD_SYMBOLS
    ]
