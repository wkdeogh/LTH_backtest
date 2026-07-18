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
            "date,open,high,low,close,adj_close,volume,price_basis\n"
            "2024-01-05,10,11,9,10,10,100,actual_split_adjusted\n"
            "2024-01-02,10,11,9,10,10,100,actual_split_adjusted\n"
            "2024-01-03,10,11,9,10,10,100,actual_split_adjusted\n",
            encoding="utf-8",
        )

        metadata = _dataset_meta(path)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["dates"], ["2024-01-02", "2024-01-03", "2024-01-05"])
        self.assertEqual(metadata["start"], "2024-01-02")
        self.assertEqual(metadata["end"], "2024-01-05")
        self.assertEqual(metadata["rows"], 3)
        self.assertEqual(metadata["price_basis"], "actual_split_adjusted")

    def test_html_defaults_and_range_controls_are_present(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="symbol" value="SOXL" checked', html)
        self.assertIn('<option value="20" selected>20분할</option>', html)
        self.assertIn('id="dateRangeStart"', html)
        self.assertIn('id="dateRangeEnd"', html)
        self.assertLess(html.index('id="backtestForm"'), html.index('id="marketDataTitle"'))
        self.assertIn("실제 거래 OHLC", html)
        self.assertIn("ACTUAL OHLCV", html)

    def test_candlestick_uses_visible_ohlc_bodies_and_korean_colors(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn('CANDLE_COLORS = Object.freeze({ rise: "#e43f45", fall: "#1976d2"', javascript)
        self.assertIn("const bodyHeight = Math.max(rawBodyHeight, minimumBodyHeight);", javascript)
        self.assertIn("ctx.moveTo(x, priceY(item.high)); ctx.lineTo(x, priceY(item.low));", javascript)
        self.assertIn("상승 · 빨강", html)
        self.assertIn("하락 · 파랑", html)
        self.assertIn(".candle-up::before { background: #e43f45; }", stylesheet)
        self.assertIn(".candle-down::before { background: #1976d2; }", stylesheet)

    def test_round_mdd_and_round_start_visualizations_are_present(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("종가 MDD</th><th>체결", html)
        self.assertIn('id="roundStartTimelineChart"', html)
        self.assertIn('id="roundStartScatterChart"', html)
        self.assertIn("function drawRoundStartTimelineChart()", javascript)
        self.assertIn("function drawRoundStartScatterChart()", javascript)
        self.assertIn("item.mdd_peak_date", javascript)
        self.assertIn(".round-start-visuals", stylesheet)

    def test_equity_tooltip_shows_return_from_initial_principal(self) -> None:
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("Number(point.equity) / initialEquity - 1", javascript)
        self.assertIn("<br>수익률 ${percent(profitRate, 2, true)}", javascript)
        self.assertNotIn("<br>낙폭 ${percent(point.drawdown)}", javascript)


if __name__ == "__main__":
    unittest.main()
