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
        self.assertIn('id="randomizeDateRange"', html)
        self.assertLess(html.index('id="backtestForm"'), html.index('id="marketDataTitle"'))
        self.assertIn("실제 OHLC", html)
        self.assertIn('id="candleBasisEyebrow"', html)
        self.assertIn('id="candleBasisDescription"', html)
        self.assertIn('id="candleBasisNote"', html)

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
        self.assertIn('actual ? "ACTUAL OHLCV" : "INPUT OHLCV"', javascript)
        self.assertIn("실제 거래가격으로 단정하지 않습니다", javascript)

    def test_round_mdd_and_round_start_visualizations_are_present(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("종가 MDD</th><th>종목 거치식</th><th>체결", html)
        self.assertIn('id="roundStartTimelineChart"', html)
        self.assertIn('id="roundStartScatterChart"', html)
        self.assertIn("function drawRoundStartTimelineChart()", javascript)
        self.assertIn("function drawRoundStartScatterChart()", javascript)
        self.assertIn("item.mdd_peak_date", javascript)
        self.assertIn("item.benchmark_profit_rate", javascript)
        self.assertIn("item.recovery_trading_days", javascript)
        self.assertIn("item.max_loss_from_start", javascript)
        self.assertIn(".round-start-visuals", stylesheet)
        self.assertIn("grid-template-columns: minmax(0,1fr)", stylesheet)
        self.assertIn(".round-chart-wrap { position: relative; width: 100%; height: 360px; }", stylesheet)

    def test_equity_tooltip_shows_each_curve_return_from_initial_principal(self) -> None:
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("function showSeriesTooltip(event, tooltipSelector, options = {})", javascript)
        self.assertIn("Number(value) / principal - 1", javascript)
        self.assertIn("{ includeReturn: true }", javascript)
        self.assertIn('key: "benchmark_equity"', javascript)
        self.assertIn('key: "qld_benchmark_equity"', javascript)
        self.assertNotIn("<br>낙폭 ${percent(point.drawdown)}", javascript)

    def test_previous_high_modes_datasets_and_payload_are_wired(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('name="analysis_mode" value="lth_v4" checked', html)
        self.assertIn('name="analysis_mode" value="previous_high"', html)
        self.assertIn('name="analysis_mode" value="compare"', html)
        self.assertIn('id="previousHighSettings"', html)
        self.assertIn('id="previousHighDatasetFields"', html)
        self.assertIn('id="lthDatasetFields" data-analysis-modes="lth_v4"', html)
        self.assertIn('id="compareV4SymbolNote" data-analysis-modes="compare"', html)
        self.assertIn("function syncAnalysisMode(refreshDatasets = true)", javascript)
        self.assertIn("function intersectTradingDates(left, right)", javascript)
        self.assertIn("function randomizeDateRange()", javascript)
        self.assertIn("Math.random() * dates.length", javascript)
        self.assertIn('addEventListener("click", randomizeDateRange)', javascript)
        self.assertIn("analysis_mode: raw.analysis_mode || selectedAnalysisMode()", javascript)
        self.assertIn("soxx_csv_path: raw.soxx_csv_path", javascript)
        self.assertIn("soxl_csv_path: raw.soxl_csv_path", javascript)
        self.assertIn("fractional_shares: Boolean(form.elements.fractional_shares?.checked)", javascript)
        self.assertIn('symbol: raw.symbol || "SOXL"', javascript)
        self.assertIn("split_count: Number(raw.split_count || 20)", javascript)
        self.assertIn('fill_model: raw.fill_model || "intraday_high"', javascript)

    def test_six_strategy_comparison_random_cards_and_sweep_visuals_are_integrated(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function renderComparison(result)", javascript)
        self.assertIn('id="comparisonYearSummary"', html)
        self.assertIn('annual.previous_high_over_soxx_rate', javascript)
        self.assertIn("function drawComparisonCharts()", javascript)
        self.assertIn("dashboardComparison.strategy_order", javascript)
        self.assertIn("result.comparison || result.benchmarks", javascript)
        self.assertIn("function comparisonSeries(comparison", javascript)
        self.assertIn('tqqq_buy_hold: { key: "tqqq_buy_hold", label: "TQQQ 거치식"', javascript)
        self.assertIn('qld_buy_hold: { key: "qld_buy_hold", label: "QLD 거치식"', javascript)
        self.assertIn('infinite_v4: { key: "infinite_v4", label: "무한매수법 V4", color: "#7651b8", lineWidth: 2, dash: [] }', javascript)
        self.assertNotIn("dash: [8, 4]", javascript)
        self.assertNotIn("dash: [3, 3]", javascript)
        self.assertNotIn("dash: [11, 4, 2, 4]", javascript)
        self.assertIn('key: `${item.key}_drawdown`', javascript)
        self.assertIn('id="comparisonEquityLegend"', html)
        self.assertIn('id="comparisonDrawdownLegend"', html)
        self.assertIn('id="randomComparisonTab" data-tab="random" data-analysis-modes="lth_v4 compare"', html)
        self.assertIn('id="randomStrategySettings" data-analysis-modes="compare"', html)
        self.assertIn('name="count" type="number" min="1" max="5000"', html)
        self.assertIn('api("/api/random/jobs", body)', javascript)
        self.assertIn('api(`/api/random/jobs/${app.randomJob.job_id}`)', javascript)
        self.assertIn("function renderRandomProgress(job, strategyComparison)", javascript)
        self.assertIn("random-progress-track", stylesheet)
        self.assertIn("random-progress-stats", stylesheet)
        self.assertIn("function renderStrategyRandom(result)", javascript)
        self.assertIn('result.result_type === "strategy_random_comparison"', javascript)
        self.assertIn("strategy-random-card", stylesheet)
        self.assertIn("strategy-random-table", stylesheet)
        self.assertIn("function renderPreviousHighAnalytics(result)", javascript)
        self.assertIn("function drawPreviousHighScatter()", javascript)
        self.assertIn('api("/api/parameter-sweep", payload)', javascript)
        self.assertIn("function drawHeatmap(canvas, matrix, axes, options = {})", javascript)
        self.assertIn("app.candleBars = normalizedMarketBars(result, app.candleSymbol)", javascript)
        self.assertIn("min-height: 360px", stylesheet)

    def test_comparison_renders_five_observational_hypotheses_safely(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="comparisonHypothesisGrid"', html)
        self.assertIn("핵심 가설 관찰 결과", html)
        self.assertIn("인과 증명 아님", html)
        self.assertIn("function renderHypothesisChecks(comparison)", javascript)
        self.assertIn("function hypothesisPresentation(item)", javascript)
        self.assertIn("Number(item.id) >= 1 && Number(item.id) <= 5", javascript)
        self.assertIn("item.previous_high_mdd", javascript)
        self.assertIn("item.recovery_conversion_count", javascript)
        self.assertIn("item.interpretation", javascript)
        self.assertIn("escapeHtml(view.scope)", javascript)
        self.assertIn("escapeHtml(view.interpretation)", javascript)
        self.assertIn(".hypothesis-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr))", stylesheet)
        self.assertIn(".hypothesis-grid { grid-template-columns: minmax(0,1fr); }", stylesheet)


if __name__ == "__main__":
    unittest.main()
