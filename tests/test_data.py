from __future__ import annotations

import tempfile
import unittest
import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from lth_backtest.data import (
    DOWNLOAD_SYMBOLS,
    FULL_HISTORY_START_DATE,
    PRICE_BASIS_ACTUAL,
    download_all_prices,
    download_prices,
    load_prices,
)


class DataValidationTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "prices.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_standard_yahoo_csv_preserves_split_adjusted_actual_ohlc(self) -> None:
        path = self.write(
            "Date,Open,High,Low,Close,Adj Close,Volume\n"
            "2024-01-02,100,110,90,100,50,1000\n"
            "2024-01-03,52,55,48,50,50,1100\n"
        )
        bars, diagnostics = load_prices(path, "2024-01-01", "2024-01-03")
        self.assertEqual(bars[0].open, Decimal("100.000000"))
        self.assertEqual(bars[0].high, Decimal("110.000000"))
        self.assertEqual(bars[0].low, Decimal("90.000000"))
        self.assertEqual(bars[0].close, Decimal("100.000000"))
        self.assertEqual(bars[0].adj_close, Decimal("50.000000"))
        self.assertEqual(diagnostics["adjusted_close_diff_rows"], 1)
        self.assertEqual(diagnostics["auto_adjusted_ohlc_rows"], 0)
        self.assertEqual(diagnostics["dividend_adjustment"], "not_applied_to_ohlc")

    def test_download_preserves_yahoo_quote_ohlc_and_labels_basis(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "SOXL.csv"
        payload = {
            "chart": {
                "error": None,
                "result": [{
                    "timestamp": [1704153600, 1704240000],
                    "indicators": {
                        "quote": [{
                            "open": [100.0, 52.0], "high": [110.0, 55.0],
                            "low": [90.0, 48.0], "close": [100.0, 50.0],
                            "volume": [1000, 1100],
                        }],
                        "adjclose": [{"adjclose": [49.5, 50.0]}],
                    },
                }],
            },
        }

        with patch("lth_backtest.data.urlopen", return_value=io.BytesIO(json.dumps(payload).encode("utf-8"))):
            download_prices("SOXL", "2024-01-02", "2024-01-03", path)

        with path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["open"], "100.000000")
        self.assertEqual(rows[0]["high"], "110.000000")
        self.assertEqual(rows[0]["low"], "90.000000")
        self.assertEqual(rows[0]["close"], "100.000000")
        self.assertEqual(rows[0]["adj_close"], "49.500000")
        self.assertEqual(rows[0]["price_basis"], PRICE_BASIS_ACTUAL)

    def test_managed_legacy_adjusted_dataset_requires_refresh(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "SOXL.csv"
        path.write_text(
            "date,open,high,low,close,adj_close,volume\n"
            "2024-01-02,10,11,9,10,10,100\n"
            "2024-01-03,10,11,9,10,10,100\n",
            encoding="utf-8",
        )
        with patch("lth_backtest.data.DATA_ROOT", Path(directory.name)):
            with self.assertRaisesRegex(ValueError, "전체 데이터를 갱신"):
                load_prices(path, "2024-01-01", "2024-01-03")

    def test_duplicate_dates_are_rejected(self) -> None:
        path = self.write(
            "date,open,high,low,close,adj_close,volume\n"
            "2024-01-02,10,11,9,10,10,100\n"
            "2024-01-02,10,11,9,10,10,100\n"
        )
        with self.assertRaisesRegex(ValueError, "중복 거래일"):
            load_prices(path, "2024-01-01", "2024-01-03")

    def test_invalid_high_is_rejected(self) -> None:
        path = self.write(
            "date,open,high,low,close,adj_close,volume\n"
            "2024-01-02,10,9,8,10,10,100\n"
            "2024-01-03,10,11,9,10,10,100\n"
        )
        with self.assertRaisesRegex(ValueError, "고가"):
            load_prices(path, "2024-01-01", "2024-01-03")

    def test_download_all_requests_every_symbol_for_full_history(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out_dir = Path(directory.name)

        with patch("lth_backtest.data.download_prices", side_effect=lambda symbol, start, end, path: path) as download:
            paths = download_all_prices("2026-07-18", out_dir)

        self.assertEqual([path.name for path in paths], [f"{symbol}.csv" for symbol in DOWNLOAD_SYMBOLS])
        self.assertEqual(
            [(call.args[0], call.args[1], call.args[2]) for call in download.call_args_list],
            [(symbol, FULL_HISTORY_START_DATE, "2026-07-18") for symbol in DOWNLOAD_SYMBOLS],
        )


if __name__ == "__main__":
    unittest.main()
