from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.comparison import STRATEGY_META
from lth_backtest.models import PriceBar
from lth_backtest.previous_high import PreviousHighConfig
from lth_backtest.strategy_random import run_strategy_random_comparison


def bars(values: list[str], multiplier: Decimal = Decimal("1")) -> list[PriceBar]:
    result: list[PriceBar] = []
    for index, raw in enumerate(values, start=2):
        value = Decimal(raw) * multiplier
        result.append(PriceBar(f"2024-01-{index:02d}", value, value, value, value, value, 1_000_000))
    return result


class StrategyRandomComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.soxx = bars(["100", "95", "90", "96", "101", "105", "98", "108", "111", "115"])
        self.soxl = bars(["20", "18", "16", "19", "22", "24", "20", "26", "28", "30"])
        self.tqqq = bars(["40", "38", "36", "39", "42", "45", "41", "47", "49", "52"])
        self.qld = bars(["30", "29", "28", "30", "32", "34", "31", "36", "37", "39"])

    def execute(self, **overrides: object) -> dict:
        options = {
            "count": 5,
            "min_days": 3,
            "max_days": 6,
            "seed": 17,
            "v4_split_count": 20,
            "v4_initial_entry": "moc",
        }
        options.update(overrides)
        return run_strategy_random_comparison(
            PreviousHighConfig(Decimal("20000"), trigger_interval_pct=Decimal("5"), divisions=20),
            self.soxx,
            self.soxl,
            self.tqqq,
            self.qld,
            **options,
        )

    def test_six_strategies_use_identical_seeded_periods_and_fixed_settings(self) -> None:
        result = self.execute()

        self.assertEqual(result["result_type"], "strategy_random_comparison")
        self.assertEqual(result["strategy_order"], list(STRATEGY_META))
        self.assertEqual({item["key"] for item in result["summary"]}, set(STRATEGY_META))
        self.assertEqual(len(result["summary"]), 6)
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual(result["config"]["v4_split_count"], 20)
        self.assertEqual(result["config"]["trigger_interval_pct"], 5.0)
        self.assertEqual(result["config"]["divisions"], 20)
        self.assertTrue(result["methodology"]["same_period_for_all_strategies"])
        self.assertTrue(result["methodology"]["strategy_parameters_fixed_from_control_panel"])

        for row in result["rows"]:
            self.assertEqual(set(row["strategies"]), set(STRATEGY_META))
            self.assertLessEqual(row["start_date"], row["end_date"])
            self.assertGreaterEqual(row["trading_days"], 3)
            self.assertLessEqual(row["trading_days"], 6)
            for metrics in row["strategies"].values():
                self.assertLessEqual(metrics["close_mdd"], 0)
                self.assertGreaterEqual(metrics["return_rank"], 1)
                self.assertLessEqual(metrics["return_rank"], 6)

        self.assertAlmostEqual(sum(item["return_win_rate"] for item in result["summary"]), 100.0, places=6)
        self.assertAlmostEqual(sum(item["lowest_mdd_rate"] for item in result["summary"]), 100.0, places=6)
        self.assertEqual(sorted(item["average_return_rank"] for item in result["summary"]), [1, 2, 3, 4, 5, 6])

    def test_seeded_result_is_deterministic(self) -> None:
        self.assertEqual(self.execute(), self.execute())

    def test_progress_callback_reports_every_completed_sample(self) -> None:
        updates: list[tuple[int, int, str]] = []

        result = self.execute(
            count=4,
            progress_callback=lambda completed, total, context: updates.append(
                (completed, total, context["phase"])
            ),
        )

        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual(updates[0], (0, 4, "sampling"))
        self.assertEqual([item[0] for item in updates if item[2] == "backtesting"], [1, 2, 3, 4])
        self.assertEqual(updates[-1], (4, 4, "summarizing"))

    def test_invalid_sample_limits_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "1~5,000"):
            self.execute(count=5001)
        with self.assertRaisesRegex(ValueError, "최소 거래일"):
            self.execute(min_days=1)
        with self.assertRaisesRegex(ValueError, "공통 데이터"):
            self.execute(min_days=20, max_days=20)


if __name__ == "__main__":
    unittest.main()
