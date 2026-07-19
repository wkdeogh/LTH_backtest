from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.comparison import (
    HOLD_BENCHMARK_ORDER,
    STRATEGY_META,
    _buy_and_hold,
    run_previous_high_hold_benchmarks,
    run_strategy_comparison,
)
from lth_backtest.models import PriceBar
from lth_backtest.previous_high import PreviousHighConfig


D = Decimal


def bar(date: str, close: str) -> PriceBar:
    value = D(close)
    return PriceBar(date, value, value, value, value, value, 1_000_000)


class StrategyComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.soxx = [
            bar("2024-01-02", "100"),
            bar("2024-01-03", "98"),
            bar("2024-01-04", "94"),
            bar("2024-01-05", "100"),
            bar("2024-01-08", "105"),
        ]
        self.soxl = [
            bar("2024-01-02", "20"),
            bar("2024-01-04", "18"),
            bar("2024-01-05", "22"),
            bar("2024-01-08", "23"),
            bar("2024-01-09", "24"),
        ]

    def test_comparison_contains_four_strategies_on_strict_common_dates(self) -> None:
        result = run_strategy_comparison(
            PreviousHighConfig(D("20000")),
            self.soxx,
            self.soxl,
            v4_initial_entry="moc",
        )
        comparison = result["comparison"]
        expected_dates = ["2024-01-02", "2024-01-04", "2024-01-05", "2024-01-08"]

        self.assertEqual(comparison["strategy_order"], list(STRATEGY_META))
        self.assertEqual(set(comparison["strategies"]), set(STRATEGY_META))
        self.assertEqual([row["date"] for row in comparison["equity_curve"]], expected_dates)
        self.assertEqual([row["date"] for row in result["market_data"]["SOXX"]], expected_dates)
        self.assertEqual([row["date"] for row in result["market_data"]["SOXL"]], expected_dates)

        for strategy_key in STRATEGY_META:
            strategy = comparison["strategies"][strategy_key]
            self.assertEqual(strategy["key"], strategy_key)
            self.assertIn("ending_equity", strategy["summary"])
            self.assertIn("total_return", strategy["metrics"])
            self.assertIn("cagr", strategy["metrics"])
            self.assertIn("close_mdd", strategy["metrics"])
            self.assertIn("sharpe_ratio", strategy["metrics"])
            for row in comparison["equity_curve"]:
                self.assertIn(strategy_key, row)
                self.assertIn(f"{strategy_key}_drawdown", row)

        self.assertEqual(comparison["strategies"]["soxx_buy_hold"]["summary"]["ending_equity"], D("21000.0000"))
        self.assertEqual(comparison["strategies"]["soxl_buy_hold"]["summary"]["ending_equity"], D("23000.0000"))
        self.assertEqual(comparison["alignment"]["common_row_count"], 4)
        self.assertEqual(comparison["alignment"]["left_only_count"], 1)
        self.assertEqual(comparison["alignment"]["right_only_count"], 1)
        self.assertEqual(comparison["alignment"]["alignment_rule"], "strict_date_intersection_no_forward_fill")
        dynamic = next(
            row for row in comparison["period_analysis"]
            if row["period"].startswith("데이터 내 SOXX 최대 낙폭")
        )
        self.assertEqual(dynamic["period"], "데이터 내 SOXX 최대 낙폭·회복")
        self.assertTrue(dynamic["recovered"])

        hypotheses = comparison["hypothesis_checks"]
        self.assertEqual([item["id"] for item in hypotheses], [1, 2, 3, 4, 5])
        for item in hypotheses:
            self.assertIsInstance(item["label"], str)
            self.assertIsInstance(item["passed"], bool)
            self.assertIn("difference_pct_points", item)
        crash_risk = hypotheses[3]
        self.assertIn("데이터 내 SOXX 최대 낙폭", crash_risk["scope"])
        self.assertFalse(crash_risk["used_overall_period"])
        self.assertFalse(crash_risk["causal_claim"])
        self.assertIn("previous_high_mdd", crash_risk)
        self.assertIn("soxx_mdd", crash_risk)
        recovery = hypotheses[4]
        self.assertEqual(recovery["completed_rounds"], result["strategy_metrics"]["total_rounds"])
        self.assertEqual(recovery["recovery_conversion_count"], result["diagnostics"]["recovery_events"])
        self.assertEqual(recovery["average_round_return"], result["strategy_metrics"]["average_round_return"])
        self.assertEqual(recovery["worst_round_return"], result["strategy_metrics"]["worst_round_return"])
        self.assertFalse(recovery["causal_claim"])
        self.assertIn("인과", recovery["interpretation"])

        annual = comparison["annual_outperformance"]
        self.assertEqual(annual["comparable_years"], len(comparison["yearly_returns"]))
        self.assertIn("best_year_vs_soxx", annual)
        self.assertIn("worst_year_vs_soxx_pct_points", annual)
        self.assertIn("best_year_vs_v4", annual)

        self.assertEqual(result["config"]["v4_split_count"], 20)
        self.assertEqual(result["config"]["v4_compounding_type"], "compound")
        self.assertIsNone(result["config"]["v4_sell_percent"])
        self.assertEqual(result["config"]["v4_effective_sell_percent"], D("20"))
        self.assertEqual(result["config"]["v4_fill_model"], "intraday_high")
        self.assertEqual(result["config"]["v4_initial_entry"], "moc")
        self.assertEqual(result["config"]["v4_first_buy_buffer_percent"], D("12"))

    def test_previous_high_dashboard_benchmarks_have_three_exact_curves(self) -> None:
        benchmarks = run_previous_high_hold_benchmarks(
            PreviousHighConfig(D("20000")), self.soxx, self.soxl,
        )

        self.assertEqual(benchmarks["strategy_order"], list(HOLD_BENCHMARK_ORDER))
        self.assertEqual(set(benchmarks["strategies"]), set(HOLD_BENCHMARK_ORDER))
        self.assertEqual([row["date"] for row in benchmarks["equity_curve"]], [
            "2024-01-02", "2024-01-04", "2024-01-05", "2024-01-08",
        ])
        for row in benchmarks["equity_curve"]:
            for key in HOLD_BENCHMARK_ORDER:
                self.assertIn(key, row)
                self.assertIn(f"{key}_drawdown", row)

    def test_dynamic_max_drawdown_period_marks_unrecovered_path(self) -> None:
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        soxx = [bar(date, close) for date, close in zip(dates, ["100", "90", "80", "70"])]
        soxl = [bar(date, close) for date, close in zip(dates, ["20", "18", "15", "12"])]

        result = run_strategy_comparison(
            PreviousHighConfig(D("20000")), soxx, soxl, v4_initial_entry="moc",
        )
        dynamic = next(
            row for row in result["comparison"]["period_analysis"]
            if row["period"].startswith("데이터 내 SOXX 최대 낙폭")
        )

        self.assertEqual(dynamic["period"], "데이터 내 SOXX 최대 낙폭·미회복")
        self.assertFalse(dynamic["recovered"])
        self.assertEqual(dynamic["start"], dates[0])
        self.assertEqual(dynamic["end"], dates[-1])

    def test_crash_risk_hypothesis_explicitly_falls_back_to_full_period(self) -> None:
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        soxx = [bar(date, close) for date, close in zip(dates, ["100", "101", "102"])]
        soxl = [bar(date, close) for date, close in zip(dates, ["20", "21", "22"])]

        result = run_strategy_comparison(
            PreviousHighConfig(D("20000")), soxx, soxl, v4_initial_entry="moc",
        )
        crash_risk = result["comparison"]["hypothesis_checks"][3]

        self.assertTrue(crash_risk["used_overall_period"])
        self.assertEqual(crash_risk["scope"], "대표 약세장 구간 없음 · 전체 기간 MDD 비교")
        self.assertIsNone(crash_risk["scope_start"])
        self.assertIsNone(crash_risk["scope_end"])

    def test_crash_risk_hypothesis_prefers_2022_bear_market_window(self) -> None:
        dates = ["2022-03-01", "2022-06-01", "2022-12-30"]
        soxx = [bar(date, close) for date, close in zip(dates, ["100", "70", "80"])]
        soxl = [bar(date, close) for date, close in zip(dates, ["20", "10", "13"])]

        result = run_strategy_comparison(
            PreviousHighConfig(D("20000")), soxx, soxl, v4_initial_entry="moc",
        )
        crash_risk = result["comparison"]["hypothesis_checks"][3]

        self.assertEqual(crash_risk["scope"], "2022 금리인상·반도체 하락")
        self.assertEqual(crash_risk["scope_start"], dates[0])
        self.assertEqual(crash_risk["scope_end"], dates[-1])
        self.assertFalse(crash_risk["used_overall_period"])

    def test_fractional_buy_and_hold_never_rounds_cash_below_zero(self) -> None:
        prices = [bar("2024-01-02", "2"), bar("2024-01-03", "2")]

        result = _buy_and_hold(
            "SOXX",
            prices,
            principal=D("10000"),
            fractional_shares=True,
            slippage_bps=D("0"),
            commission=D("0.00005"),
            annual_risk_free_rate=D("0"),
        )

        self.assertEqual(result["entry"]["shares"], D("4999.99997499"))
        self.assertEqual(result["entry"]["cash"], D("0.0001"))
        self.assertGreaterEqual(result["entry"]["cash"], D("0"))

    def test_all_strategies_use_same_principal_period_and_cost_assumptions(self) -> None:
        config = PreviousHighConfig(
            D("20000"),
            fractional_shares=True,
            slippage_bps=D("10"),
            commission=D("1"),
            sell_fee_bps=D("5"),
        )
        result = run_strategy_comparison(config, self.soxx, self.soxl, v4_initial_entry="moc")
        comparison = result["comparison"]

        self.assertEqual(result["period"]["start"], "2024-01-02")
        self.assertEqual(result["period"]["end"], "2024-01-08")
        self.assertEqual(result["period"]["trading_days"], 4)
        self.assertEqual(result["config"]["principal"], D("20000"))
        self.assertEqual(result["config"]["slippage_bps"], D("10"))
        self.assertEqual(result["config"]["commission"], D("1"))
        self.assertEqual(result["config"]["sell_fee_bps"], D("5"))
        for strategy in comparison["strategies"].values():
            self.assertGreater(strategy["summary"]["ending_equity"], D("0"))

        # Both buy-and-hold baselines pay the configured adverse entry and
        # commission; neither silently starts at the full theoretical equity.
        first_row = comparison["equity_curve"][0]
        self.assertLess(first_row["soxx_buy_hold"], D("20000"))
        self.assertLess(first_row["soxl_buy_hold"], D("20000"))

    def test_comparison_is_deterministic(self) -> None:
        config = PreviousHighConfig(D("20000"))
        first = run_strategy_comparison(config, self.soxx, self.soxl, v4_initial_entry="moc")
        second = run_strategy_comparison(config, self.soxx, self.soxl, v4_initial_entry="moc")
        self.assertEqual(first, second)

    def test_comparison_rejects_fewer_than_two_common_dates(self) -> None:
        with self.assertRaisesRegex(ValueError, "공통 거래일이 최소 2일"):
            run_strategy_comparison(
                PreviousHighConfig(D("20000")),
                [bar("2024-01-02", "100"), bar("2024-01-03", "101")],
                [bar("2024-01-02", "20"), bar("2024-01-04", "21")],
            )


if __name__ == "__main__":
    unittest.main()
