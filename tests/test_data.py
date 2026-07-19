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
    VALID_PRICE_SYMBOLS,
    align_price_series,
    download_all_prices,
    download_prices,
    load_prices,
)
from lth_backtest.models import PriceBar


class DataValidationTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "prices.csv"
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def bar(date_value: str, close: str = "100") -> PriceBar:
        value = Decimal(close)
        return PriceBar(date_value, value, value, value, value, value, 1_000)

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

    def test_download_keeps_valid_ohlc_when_adjusted_close_is_missing(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "SOXX.csv"
        payload = {
            "chart": {
                "error": None,
                "result": [{
                    "timestamp": [1704153600, 1704240000],
                    "indicators": {
                        "quote": [{
                            "open": [100.0, 101.0], "high": [102.0, 103.0],
                            "low": [99.0, 100.0], "close": [101.0, 102.0],
                            "volume": [1000, 1100],
                        }],
                        "adjclose": [{"adjclose": [None, 101.5]}],
                    },
                }],
            },
        }

        with patch("lth_backtest.data.urlopen", return_value=io.BytesIO(json.dumps(payload).encode("utf-8"))):
            download_prices("SOXX", "2024-01-02", "2024-01-03", path)

        with path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["close"], "101.000000")
        self.assertEqual(rows[0]["adj_close"], "101.000000")

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

    def test_partially_labeled_price_basis_is_rejected(self) -> None:
        path = self.write(
            "date,open,high,low,close,adj_close,volume,price_basis\n"
            "2024-01-02,10,11,9,10,10,100,actual_split_adjusted\n"
            "2024-01-03,10,11,9,10,10,100,\n"
        )
        with self.assertRaisesRegex(ValueError, "일부 행에만 price_basis"):
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

    def test_soxx_is_a_managed_download_symbol_in_stable_order(self) -> None:
        self.assertEqual(DOWNLOAD_SYMBOLS, ("TQQQ", "SOXX", "SOXL", "QLD"))
        self.assertEqual(VALID_PRICE_SYMBOLS, {"TQQQ", "SOXX", "SOXL", "QLD"})

    def test_alignment_uses_only_strict_common_dates_without_forward_fill(self) -> None:
        left = [
            self.bar("2024-01-05", "105"),
            self.bar("2024-01-02", "102"),
            self.bar("2024-01-06", "106"),
            self.bar("2024-01-03", "103"),
        ]
        right = [
            self.bar("2024-01-04", "204"),
            self.bar("2024-01-05", "205"),
            self.bar("2024-01-03", "203"),
        ]

        aligned, diagnostics = align_price_series(left, right)

        self.assertEqual([(one.date, two.date) for one, two in aligned], [
            ("2024-01-03", "2024-01-03"),
            ("2024-01-05", "2024-01-05"),
        ])
        self.assertEqual([pair[1].close for pair in aligned], [Decimal("203"), Decimal("205")])
        self.assertEqual(diagnostics["alignment_rule"], "strict_date_intersection_no_forward_fill")
        self.assertEqual(diagnostics["common_row_count"], 2)
        self.assertEqual(diagnostics["common_start_date"], "2024-01-03")
        self.assertEqual(diagnostics["common_end_date"], "2024-01-05")
        self.assertEqual(diagnostics["left_only_count"], 2)
        self.assertEqual(diagnostics["right_only_count"], 1)
        self.assertEqual(diagnostics["left_only_date_samples"], ["2024-01-02", "2024-01-06"])
        self.assertEqual(diagnostics["right_only_date_samples"], ["2024-01-04"])

    def test_alignment_rejects_duplicate_dates(self) -> None:
        left = [self.bar("2024-01-02"), self.bar("2024-01-02"), self.bar("2024-01-03")]
        right = [self.bar("2024-01-02"), self.bar("2024-01-03")]

        with self.assertRaisesRegex(ValueError, "SOXX.*중복 거래일"):
            align_price_series(left, right)

    def test_alignment_requires_two_common_dates(self) -> None:
        left = [self.bar("2024-01-02"), self.bar("2024-01-03")]
        right = [self.bar("2024-01-03"), self.bar("2024-01-04")]

        with self.assertRaisesRegex(ValueError, "공통 거래일이 최소 2일"):
            align_price_series(left, right)


if __name__ == "__main__":
    unittest.main()
