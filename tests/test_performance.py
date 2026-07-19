from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.performance import calculate_equity_performance


D = Decimal


class EquityPerformanceTests(unittest.TestCase):
    def test_mdd_recovery_period_returns_and_year_statistics(self) -> None:
        curve = [
            {"date": "2023-12-29", "equity": D("100")},
            {"date": "2024-01-02", "equity": D("120")},
            {"date": "2024-01-03", "equity": D("90")},
            {"date": "2024-01-05", "equity": D("110")},
            {"date": "2024-01-08", "equity": D("120")},
            {"date": "2024-12-31", "equity": D("132")},
        ]

        metrics, monthly, yearly = calculate_equity_performance(curve, D("100"), D("0"))

        self.assertEqual(metrics["ending_equity"], D("132.0000"))
        self.assertEqual(metrics["total_return"], D("32.00000000"))
        self.assertEqual(metrics["close_mdd"], D("-25.00000000"))
        self.assertEqual(metrics["mdd_peak_date"], "2024-01-02")
        self.assertEqual(metrics["mdd_trough_date"], "2024-01-03")
        self.assertEqual(metrics["mdd_recovery_date"], "2024-01-08")
        self.assertTrue(metrics["mdd_recovered"])
        self.assertEqual(metrics["mdd_decline_calendar_days"], 1)
        self.assertEqual(metrics["mdd_decline_trading_days"], 1)
        self.assertEqual(metrics["mdd_recovery_calendar_days"], 5)
        self.assertEqual(metrics["mdd_recovery_trading_days"], 2)
        self.assertEqual(metrics["mdd_underwater_calendar_days"], 6)
        self.assertEqual(metrics["mdd_underwater_trading_days"], 3)
        self.assertEqual(
            [point["drawdown"] for point in curve],
            [D("0E-8"), D("0E-8"), D("-25.00000000"), D("-8.33333333"), D("0E-8"), D("0E-8")],
        )

        self.assertEqual([(row["period"], row["return_rate"]) for row in monthly], [
            ("2023-12", D("0E-8")),
            ("2024-01", D("20.00000000")),
            ("2024-12", D("10.00000000")),
        ])
        self.assertEqual([(row["period"], row["return_rate"]) for row in yearly], [
            ("2023", D("0E-8")),
            ("2024", D("32.00000000")),
        ])
        self.assertEqual(metrics["best_year"], "2024")
        self.assertEqual(metrics["best_yearly_return"], D("32.00000000"))
        self.assertEqual(metrics["worst_year"], "2023")
        self.assertEqual(metrics["worst_yearly_return"], D("0E-8"))
        self.assertEqual(metrics["positive_year_count"], 1)
        self.assertEqual(metrics["year_count"], 2)
        self.assertEqual(metrics["positive_year_ratio"], D("50.00000000"))
        self.assertEqual(metrics["cagr"], D("31.72567899"))
        self.assertEqual(metrics["annual_volatility"], D("300.96148343"))
        self.assertEqual(metrics["sharpe_ratio"], D("6.08111642"))
        self.assertEqual(metrics["sortino_ratio"], D("10.31190634"))
        self.assertEqual(metrics["calmar_ratio"], D("1.26902716"))
        self.assertEqual(metrics["sharpe_ratio_status"], "finite")
        self.assertEqual(metrics["sortino_ratio_status"], "finite")
        self.assertEqual(metrics["calmar_ratio_status"], "finite")
        self.assertEqual(metrics["longest_underwater_calendar_days"], 3)
        self.assertEqual(metrics["longest_underwater_trading_days"], 2)

    def test_unrecovered_mdd_reports_open_underwater_period_through_last_day(self) -> None:
        curve = [
            {"date": "2024-01-02", "equity": D("100")},
            {"date": "2024-01-03", "equity": D("80")},
            {"date": "2024-01-08", "equity": D("90")},
        ]

        metrics, _, _ = calculate_equity_performance(curve, D("100"), D("0"))

        self.assertEqual(metrics["close_mdd"], D("-20.00000000"))
        self.assertIsNone(metrics["mdd_recovery_date"])
        self.assertFalse(metrics["mdd_recovered"])
        self.assertIsNone(metrics["mdd_recovery_calendar_days"])
        self.assertIsNone(metrics["mdd_recovery_trading_days"])
        self.assertEqual(metrics["mdd_underwater_calendar_days"], 6)
        self.assertEqual(metrics["mdd_underwater_trading_days"], 2)

    def test_custom_equity_key_is_supported_and_mutates_drawdown(self) -> None:
        curve = [
            {"date": "2024-01-02", "strategy_equity": D("100")},
            {"date": "2024-01-03", "strategy_equity": D("110")},
        ]

        metrics, monthly, yearly = calculate_equity_performance(
            curve,
            D("100"),
            D("3.5"),
            equity_key="strategy_equity",
        )

        self.assertEqual(metrics["total_return"], D("10.00000000"))
        self.assertEqual([point["drawdown"] for point in curve], [D("0E-8"), D("0E-8")])
        self.assertEqual(monthly[0]["ending_equity"], D("110.0000"))
        self.assertEqual(yearly[0]["return_rate"], D("10.00000000"))
        self.assertEqual(metrics["sharpe_ratio"], D("0E-8"))
        self.assertEqual(metrics["sharpe_ratio_status"], "undefined_zero_volatility")
        self.assertEqual(metrics["sortino_ratio_status"], "unbounded_no_downside")
        self.assertEqual(metrics["calmar_ratio_status"], "unbounded_no_drawdown")

    def test_empty_curve_and_invalid_inputs_are_deterministic(self) -> None:
        self.assertEqual(calculate_equity_performance([], D("100"), D("0")), ({}, [], []))
        with self.assertRaisesRegex(ValueError, "원금은 0보다"):
            calculate_equity_performance([{"date": "2024-01-02", "equity": D("100")}], D("0"), D("0"))
        with self.assertRaisesRegex(ValueError, "오름차순"):
            calculate_equity_performance([
                {"date": "2024-01-03", "equity": D("100")},
                {"date": "2024-01-02", "equity": D("101")},
            ], D("100"), D("0"))


if __name__ == "__main__":
    unittest.main()
