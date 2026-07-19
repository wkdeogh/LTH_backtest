from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.models import PriceBar
from lth_backtest.parameter_sweep import _percentile_scores, run_parameter_sweep
from lth_backtest.previous_high import PreviousHighConfig, run_previous_high_backtest


D = Decimal


def bars(values: list[str], *, leveraged: bool = False) -> list[PriceBar]:
    dates = (
        "2024-01-02", "2024-01-03", "2024-01-04",
        "2024-01-05", "2024-01-08", "2024-01-09",
        "2024-01-10", "2024-01-11", "2024-01-12",
    )
    result: list[PriceBar] = []
    for date, raw in zip(dates, values):
        value = D(raw)
        result.append(PriceBar(date, value, value, value, value, value, 1_000_000 if not leveraged else 2_000_000))
    return result


class ParameterSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.soxx = bars(["100", "94", "90", "100", "105", "99", "110", "100", "112"])
        self.soxl = bars(["20", "18", "17", "22", "23", "21", "25", "22", "26"], leveraged=True)
        self.config = PreviousHighConfig(D("20000"), trigger_interval_pct=D("5"), divisions=20)

    def test_baseline_cell_matches_standalone_backtest_exactly(self) -> None:
        standalone = run_previous_high_backtest(self.config, self.soxx, self.soxl)
        sweep = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("10"), D("5")],
            divisions=[20, 10],
        )
        baseline = sweep["baseline"]

        self.assertIsNotNone(baseline)
        assert baseline is not None
        self.assertEqual(baseline["trigger_interval_pct"], D("5"))
        self.assertEqual(baseline["divisions"], 20)
        self.assertEqual(baseline["ending_equity"], standalone["summary"]["ending_equity"])
        self.assertEqual(baseline["total_return"], standalone["metrics"]["total_return"])
        self.assertEqual(baseline["cagr"], standalone["metrics"]["cagr"])
        self.assertEqual(baseline["close_mdd"], standalone["metrics"]["close_mdd"])
        self.assertEqual(baseline["calmar_ratio"], standalone["metrics"]["calmar_ratio"])
        self.assertEqual(baseline["sharpe_ratio"], standalone["metrics"]["sharpe_ratio"])
        self.assertEqual(baseline["max_soxl_weight"], standalone["strategy_metrics"]["max_soxl_weight"])
        self.assertEqual(baseline["max_effective_leverage"], standalone["strategy_metrics"]["max_effective_leverage"])
        self.assertEqual(baseline["completed_rounds"], standalone["summary"]["completed_rounds"])
        self.assertEqual(baseline["conversion_events"], standalone["strategy_metrics"]["conversion_event_count"])

        # The sweep must not mutate the caller's baseline configuration.
        self.assertEqual(self.config.trigger_interval_pct, D("5"))
        self.assertEqual(self.config.divisions, 20)

    def test_sweep_records_input_price_basis_for_reproducibility(self) -> None:
        diagnostics = {
            "SOXX": {"price_basis": "actual_split_adjusted"},
            "SOXL": {"price_basis": "actual_split_adjusted"},
        }
        sweep = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("5")],
            divisions=[20],
            include_subperiods=False,
            data_diagnostics=diagnostics,
        )

        self.assertEqual(sweep["config"]["price_basis"], "actual_split_adjusted")

    def test_axes_rows_heatmaps_and_periods_have_stable_order(self) -> None:
        sweep = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("10"), D("5")],
            divisions=[20, 10],
        )

        self.assertEqual(sweep["axes"]["intervals"], [D("5"), D("10")])
        self.assertEqual(sweep["axes"]["divisions"], [10, 20])
        self.assertEqual(
            [(row["trigger_interval_pct"], row["divisions"]) for row in sweep["rows"]],
            [(D("5"), 10), (D("5"), 20), (D("10"), 10), (D("10"), 20)],
        )
        self.assertEqual([row["name"] for row in sweep["periods"]], ["전체", "초기 1/3", "중간 1/3", "최근 1/3"])
        self.assertEqual([row["trading_days"] for row in sweep["periods"]], [9, 3, 3, 3])

        indexed = {
            (row["trigger_interval_pct"], row["divisions"]): row
            for row in sweep["rows"]
        }
        for row_index, interval in enumerate(sweep["axes"]["intervals"]):
            for column_index, division in enumerate(sweep["axes"]["divisions"]):
                row = indexed[(interval, division)]
                self.assertEqual(sweep["heatmaps"]["cagr"][row_index][column_index], row["cagr"])
                self.assertEqual(sweep["heatmaps"]["close_mdd"][row_index][column_index], row["close_mdd"])
                self.assertEqual(sweep["heatmaps"]["calmar_ratio"][row_index][column_index], row["calmar_ratio"])
                self.assertGreaterEqual(row["robustness_score"], D("0"))
                self.assertLessEqual(row["robustness_score"], D("100"))
                self.assertGreaterEqual(row["stability_score"], D("0"))
                self.assertLessEqual(row["stability_score"], D("100"))

    def test_sweep_is_deterministic_and_candidate_input_order_independent(self) -> None:
        first = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("10"), D("5")],
            divisions=[20, 10],
        )
        repeated = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("10"), D("5")],
            divisions=[20, 10],
        )
        reordered = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("5"), D("10")],
            divisions=[10, 20],
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first, reordered)

    def test_subperiod_validation_can_be_disabled_without_changing_full_result(self) -> None:
        with_subperiods = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("5")],
            divisions=[20],
        )
        full_only = run_parameter_sweep(
            self.config,
            self.soxx,
            self.soxl,
            intervals=[D("5")],
            divisions=[20],
            include_subperiods=False,
        )

        self.assertEqual([period["name"] for period in full_only["periods"]], ["전체"])
        self.assertEqual(full_only["rows"][0]["ending_equity"], with_subperiods["rows"][0]["ending_equity"])
        self.assertEqual(full_only["rows"][0]["cagr"], with_subperiods["rows"][0]["cagr"])
        self.assertEqual(set(full_only["rows"][0]["period_metrics"]), {"전체"})
        self.assertFalse(full_only["methodology"]["subperiod_validation"])

    def test_flat_parameter_plateau_receives_neutral_tie_aware_score(self) -> None:
        # With no drawdown, no candidate can trigger a conversion.  Every cell
        # therefore has exactly the same performance and should form a neutral,
        # perfectly stable plateau instead of all being ranked at zero.
        flat_soxx = bars(["100"] * 9)
        flat_soxl = bars(["20"] * 9, leveraged=True)
        sweep = run_parameter_sweep(
            self.config,
            flat_soxx,
            flat_soxl,
            intervals=[D("5"), D("10")],
            divisions=[10, 20],
        )

        self.assertEqual(len(sweep["rows"]), 4)
        self.assertTrue(all(row["robustness_score"] == D("50") for row in sweep["rows"]))
        self.assertTrue(all(row["neighbor_cagr_spread"] == D("0") for row in sweep["rows"]))
        self.assertTrue(all(row["neighbor_calmar_spread"] == D("0") for row in sweep["rows"]))
        self.assertTrue(all(row["stability_score"] == D("50") for row in sweep["rows"]))

    def test_robustness_combines_cagr_and_calmar_as_independent_equal_weight_ranks(self) -> None:
        rows = [
            {"trigger_interval_pct": D("3"), "divisions": 20, "period_metrics": {"전체": {"calmar_ratio": D("3"), "cagr": D("1")}}},
            {"trigger_interval_pct": D("5"), "divisions": 20, "period_metrics": {"전체": {"calmar_ratio": D("2"), "cagr": D("3")}}},
            {"trigger_interval_pct": D("7"), "divisions": 20, "period_metrics": {"전체": {"calmar_ratio": D("1"), "cagr": D("2")}}},
        ]

        _percentile_scores(rows, ["전체"])

        self.assertEqual([row["robustness_score"] for row in rows], [D("50.00000000"), D("75.00000000"), D("25.00000000")])

    def test_candidate_validation_rejects_empty_duplicate_or_out_of_range_axes(self) -> None:
        invalid_cases = (
            ([], [20]),
            ([D("5")], []),
            ([D("5"), D("5")], [20]),
            ([D("5")], [20, 20]),
            ([D("0")], [20]),
            ([D("100")], [20]),
            ([D("5")], [1]),
            ([D("5")], [501]),
            ([D(index) for index in range(1, 22)], [20]),
            ([D("5")], list(range(2, 23))),
        )
        for intervals, divisions in invalid_cases:
            with self.subTest(intervals=intervals, divisions=divisions):
                with self.assertRaises(ValueError):
                    run_parameter_sweep(
                        self.config,
                        self.soxx,
                        self.soxl,
                        intervals=intervals,
                        divisions=divisions,
                    )


if __name__ == "__main__":
    unittest.main()
