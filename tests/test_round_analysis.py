from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from lth_backtest.engine import run_backtest
from lth_backtest.models import BacktestConfig, PriceBar
from lth_backtest.round_analysis import run_round_start_analysis


D = Decimal


def bar(date: str, close: str, high: str | None = None) -> PriceBar:
    close_value = D(close)
    high_value = D(high or close)
    return PriceBar(date, close_value, high_value, close_value, close_value, close_value, 1_000_000)


class RoundStartAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = BacktestConfig("TQQQ", 40, D("20000"))
        self.prices = [
            bar("2024-01-02", "100"),
            bar("2024-01-03", "115", "116"),
            bar("2024-01-04", "132.25", "133"),
        ]

    def test_backtest_can_stop_exactly_after_first_completed_round(self) -> None:
        result = run_backtest(self.config, self.prices, stop_after_completed_rounds=1)

        self.assertEqual(len(result.rounds), 1)
        self.assertEqual(result.period["end"], "2024-01-03")
        self.assertEqual(result.period["trading_days"], 2)
        self.assertTrue(all(execution.round_number == 1 for execution in result.executions))

    def test_every_trading_day_is_an_independent_round_start(self) -> None:
        result = run_round_start_analysis(self.config, self.prices)
        rows = result["rows"]

        self.assertEqual([row["start_date"] for row in rows], [item.date for item in self.prices])
        self.assertEqual([row["completed"] for row in rows], [True, True, False])
        self.assertEqual(rows[0]["end_date"], "2024-01-03")
        self.assertEqual(rows[1]["end_date"], "2024-01-04")
        self.assertIsNone(rows[2]["end_date"])
        self.assertEqual(rows[2]["last_observed_at"], "2024-01-04")
        self.assertEqual(rows[0]["buy_count"], 1)
        self.assertEqual(rows[0]["sell_count"], 2)
        self.assertEqual(rows[0]["max_t_value"], D("1.0000000000"))

    def test_incomplete_samples_are_excluded_from_completed_averages(self) -> None:
        summary = run_round_start_analysis(self.config, self.prices)["summary"]

        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["incomplete_count"], 1)
        self.assertEqual(summary["completion_rate"], D("66.66666667"))
        self.assertEqual(summary["avg_profit_rate_completed"], D("0.36000000"))
        self.assertEqual(summary["completed_win_rate"], D("100.00000000"))

    def test_maximum_t_and_reverse_entry_are_preserved(self) -> None:
        prices = []
        price = D("100")
        for index in range(45):
            value = price.quantize(D("0.000001"))
            date_value = str(date(2024, 1, 1) + timedelta(days=index))
            prices.append(PriceBar(date_value, value, value, value, value, value, 1_000_000))
            price *= D("0.90")

        row = run_round_start_analysis(BacktestConfig("TQQQ", 20, D("20000")), prices)["rows"][0]

        self.assertFalse(row["completed"])
        self.assertTrue(row["reverse_entered"])
        self.assertEqual(row["reverse_entries"], 1)
        self.assertEqual(row["max_t_value"], D("20.0000000000"))
        self.assertEqual(row["ending_mode"], "reverse")


if __name__ == "__main__":
    unittest.main()
