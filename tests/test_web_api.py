from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lth_backtest.web import _previous_high_config, _run_payload, _run_sweep_payload


class PreviousHighWebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.soxx = root / "SOXX.csv"
        self.soxl = root / "SOXL.csv"
        dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
        soxx = [(100, 100), (96, 94), (96, 96), (94, 94), (89, 89), (101, 101)]
        soxl = [20, 20, 21, 20, 18, 22]
        header = "date,open,high,low,close,adj_close,volume,price_basis\n"
        self.soxx.write_text(
            header + "".join(
                f"{date},{open_},{max(open_, close)},{min(open_, close)},{close},{close},1,actual_split_adjusted\n"
                for date, (open_, close) in zip(dates, soxx)
            ),
            encoding="utf-8",
        )
        self.soxl.write_text(
            header + "".join(
                f"{date},{price},{price},{price},{price},{price},1,actual_split_adjusted\n"
                for date, price in zip(dates, soxl)
            ),
            encoding="utf-8",
        )
        self.payload = {
            "analysis_mode": "compare",
            "principal": "20000",
            "start_date": dates[0],
            "end_date": dates[-1],
            "soxx_csv_path": str(self.soxx),
            "soxl_csv_path": str(self.soxl),
            "trigger_interval_pct": "5",
            "divisions": 20,
            "split_count": 20,
        }

    def test_previous_high_config_has_documented_defaults_and_boolean_parsing(self) -> None:
        config = _previous_high_config({"principal": "10000", "fractional_shares": "on"})
        self.assertEqual(str(config.trigger_interval_pct), "5")
        self.assertEqual(config.divisions, 20)
        self.assertTrue(config.fractional_shares)
        self.assertEqual(str(config.liquidation_offset_pct), "0")

    def test_run_payload_returns_tagged_four_strategy_comparison(self) -> None:
        result = _run_payload(self.payload)
        self.assertEqual(result["result_type"], "comparison")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["summary"]["ending_equity"], 20308.0)
        self.assertEqual(
            set(result["comparison"]["strategies"]),
            {"previous_high", "infinite_v4", "soxx_buy_hold", "soxl_buy_hold"},
        )
        self.assertEqual(result["period"]["trading_days"], 6)
        self.assertEqual(len(result["market_data"]["SOXX"]), 6)
        self.assertEqual(result["config"]["price_basis"], "actual_split_adjusted")

    def test_previous_high_single_mode_does_not_compute_hidden_comparison(self) -> None:
        payload = dict(self.payload, analysis_mode="previous_high")
        result = _run_payload(payload)
        self.assertEqual(result["result_type"], "previous_high")
        self.assertNotIn("comparison", result)
        self.assertEqual(
            result["benchmarks"]["strategy_order"],
            ["previous_high", "soxx_buy_hold", "soxl_buy_hold"],
        )
        self.assertEqual(len(result["benchmarks"]["equity_curve"]), 6)
        self.assertEqual(len(result["market_data"]["SOXX"]), 6)
        self.assertEqual(len(result["market_data"]["SOXL"]), 6)
        self.assertEqual(result["config"]["price_basis"], "actual_split_adjusted")

    def test_sweep_payload_accepts_ui_divisions_field(self) -> None:
        payload = dict(self.payload, intervals=["5", "6"], divisions=[20])
        result = _run_sweep_payload(payload)
        self.assertEqual(result["result_type"], "parameter_sweep")
        self.assertEqual(result["axes"], {"intervals": [5.0, 6.0], "divisions": [20]})
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["config"]["price_basis"], "actual_split_adjusted")

    def test_sweep_payload_honors_subperiod_toggle(self) -> None:
        payload = dict(
            self.payload,
            intervals=["5"],
            divisions=[20],
            subperiod_validation=False,
        )
        result = _run_sweep_payload(payload)
        self.assertEqual([period["name"] for period in result["periods"]], ["전체"])
        self.assertFalse(result["methodology"]["subperiod_validation"])

    def test_mixed_price_basis_is_rejected(self) -> None:
        text = self.soxl.read_text(encoding="utf-8").replace("actual_split_adjusted", "user_provided")
        self.soxl.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "가격 기준"):
            _run_payload(self.payload)


if __name__ == "__main__":
    unittest.main()
