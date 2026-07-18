from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lth_backtest.web import STATIC_ROOT, _config, _dataset_meta


class WebConfigurationTests(unittest.TestCase):
    def test_default_strategy_is_soxl_20_split(self) -> None:
        config = _config({})
        self.assertEqual(config.symbol, "SOXL")
        self.assertEqual(config.split_count, 20)

    def test_dataset_metadata_exposes_sorted_trading_dates(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "SOXL.csv"
        path.write_text(
            "date,open,high,low,close,adj_close,volume\n"
            "2024-01-05,10,11,9,10,10,100\n"
            "2024-01-02,10,11,9,10,10,100\n"
            "2024-01-03,10,11,9,10,10,100\n",
            encoding="utf-8",
        )

        metadata = _dataset_meta(path)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["dates"], ["2024-01-02", "2024-01-03", "2024-01-05"])
        self.assertEqual(metadata["start"], "2024-01-02")
        self.assertEqual(metadata["end"], "2024-01-05")
        self.assertEqual(metadata["rows"], 3)

    def test_html_defaults_and_range_controls_are_present(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="symbol" value="SOXL" checked', html)
        self.assertIn('<option value="20" selected>20분할</option>', html)
        self.assertIn('id="dateRangeStart"', html)
        self.assertIn('id="dateRangeEnd"', html)
        self.assertLess(html.index('id="backtestForm"'), html.index('id="marketDataTitle"'))


if __name__ == "__main__":
    unittest.main()
