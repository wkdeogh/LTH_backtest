from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from lth_backtest.random_compare import run_random_comparison


class LthRandomComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        dates = [f"2024-01-{day:02d}" for day in range(1, 11)]
        prices = {
            "QLD": [30, 31, 29, 32, 33, 31, 35, 34, 37, 39],
            "TQQQ": [40, 42, 39, 44, 46, 43, 49, 47, 53, 56],
            "SOXL": [20, 21, 19, 23, 24, 22, 26, 25, 29, 31],
        }
        header = "date,open,high,low,close,adj_close,volume,price_basis\n"
        for symbol, values in prices.items():
            (self.root / f"{symbol}.csv").write_text(
                header + "".join(
                    f"{date},{value},{value},{value},{value},{value},1,actual_split_adjusted\n"
                    for date, value in zip(dates, values)
                ),
                encoding="utf-8",
            )

    def execute(self, **overrides) -> dict:
        options = {
            "symbols": ["TQQQ", "SOXL"],
            "splits": [20, 40],
            "principal": Decimal("20000"),
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "count": 4,
            "min_days": 3,
            "csv_dir": self.root,
        }
        options.update(overrides)
        return run_random_comparison(**options)

    def test_uniform_sampling_uses_even_fixed_common_windows_for_every_combination(self) -> None:
        result = self.execute(
            max_days=2,
            seed=99,
            uniform_start_sampling=True,
        )

        self.assertEqual(result["result_type"], "lth_random_comparison")
        self.assertEqual(
            [(row["start_date"], row["end_date"], row["trading_days"]) for row in result["sample_rows"]],
            [
                ("2024-01-01", "2024-01-03", 3),
                ("2024-01-03", "2024-01-05", 3),
                ("2024-01-05", "2024-01-07", 3),
                ("2024-01-07", "2024-01-09", 3),
            ],
        )
        self.assertEqual(result["combination_order"], ["tqqq_20", "tqqq_40", "soxl_20", "soxl_40"])
        self.assertTrue(all(set(row["strategies"]) == set(result["combination_order"]) for row in result["sample_rows"]))
        self.assertEqual(sum(item["return_win_rate"] for item in result["summary"]), 100.0)
        self.assertEqual(sum(item["lowest_mdd_rate"] for item in result["summary"]), 100.0)
        self.assertTrue(result["methodology"]["same_period_for_all_combinations"])
        self.assertTrue(result["methodology"]["seed_ignored"])

    def test_uniform_sampling_caps_requested_count_to_valid_start_dates(self) -> None:
        updates = []
        result = self.execute(
            count=50,
            uniform_start_sampling=True,
            progress_callback=lambda completed, total, context: updates.append(
                (completed, total, context["phase"])
            ),
        )

        self.assertEqual(result["config"]["requested_count"], 50)
        self.assertEqual(result["config"]["count"], 8)
        self.assertEqual(len(result["sample_rows"]), 8)
        self.assertEqual({row["trading_days"] for row in result["sample_rows"]}, {3})
        self.assertTrue(result["methodology"]["sample_count_capped"])
        self.assertIn("8개 시작일까지만", result["warnings"][-1])
        self.assertEqual(updates[0], (0, 32, "sampling"))
        self.assertEqual(updates[-1], (32, 32, "summarizing"))

    def test_seeded_random_sampling_remains_deterministic(self) -> None:
        first = self.execute(count=5, min_days=2, max_days=6, seed=71)
        second = self.execute(count=5, min_days=2, max_days=6, seed=71)

        self.assertEqual(first["sample_rows"], second["sample_rows"])
        self.assertEqual(first["summary"], second["summary"])
        self.assertFalse(first["config"]["uniform_start_sampling"])
        self.assertFalse(first["methodology"]["seed_ignored"])


if __name__ == "__main__":
    unittest.main()
