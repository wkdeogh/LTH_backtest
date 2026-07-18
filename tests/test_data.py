from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from lth_backtest.data import load_prices


class DataValidationTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "prices.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_standard_yahoo_csv_is_auto_adjusted_consistently(self) -> None:
        path = self.write(
            "Date,Open,High,Low,Close,Adj Close,Volume\n"
            "2024-01-02,100,110,90,100,50,1000\n"
            "2024-01-03,52,55,48,50,50,1100\n"
        )
        bars, diagnostics = load_prices(path, "2024-01-01", "2024-01-03")
        self.assertEqual(bars[0].open, Decimal("50.000000"))
        self.assertEqual(bars[0].high, Decimal("55.000000"))
        self.assertEqual(bars[0].low, Decimal("45.000000"))
        self.assertEqual(bars[0].close, Decimal("50.000000"))
        self.assertEqual(diagnostics["auto_adjusted_ohlc_rows"], 1)

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


if __name__ == "__main__":
    unittest.main()
