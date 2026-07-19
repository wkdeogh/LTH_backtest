from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from lth_backtest.web import (
    _previous_high_config,
    _random_job_snapshot,
    _run_payload,
    _run_random_payload,
    _run_strategy_random_payload,
    _run_sweep_payload,
    _start_random_job,
)


class PreviousHighWebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.soxx = root / "SOXX.csv"
        self.soxl = root / "SOXL.csv"
        self.tqqq = root / "TQQQ.csv"
        self.qld = root / "QLD.csv"
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
        self.qld.write_text(
            header + "".join(
                f"{date},{price},{price},{price},{price},{price},1,actual_split_adjusted\n"
                for date, price in zip(dates, [30, 29, 30, 28, 27, 32])
            ),
            encoding="utf-8",
        )
        self.tqqq.write_text(
            header + "".join(
                f"{date},{price},{price},{price},{price},{price},1,actual_split_adjusted\n"
                for date, price in zip(dates, [40, 39, 41, 38, 37, 45])
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
            "tqqq_csv_path": str(self.tqqq),
            "qld_csv_path": str(self.qld),
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

    def test_run_payload_returns_six_strategy_comparison(self) -> None:
        result = _run_payload(self.payload)
        self.assertEqual(result["result_type"], "comparison")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["summary"]["ending_equity"], 20308.0)
        self.assertEqual(
            set(result["comparison"]["strategies"]),
            {"previous_high", "infinite_v4", "soxx_buy_hold", "soxl_buy_hold", "tqqq_buy_hold", "qld_buy_hold"},
        )
        self.assertEqual(result["period"]["trading_days"], 6)
        self.assertEqual(len(result["market_data"]["SOXX"]), 6)
        self.assertEqual(len(result["market_data"]["TQQQ"]), 6)
        self.assertEqual(len(result["market_data"]["QLD"]), 6)
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

    def test_strategy_random_payload_uses_control_panel_settings_for_six_cards(self) -> None:
        payload = dict(
            self.payload,
            count=3,
            min_days=2,
            max_days=4,
            seed=11,
            split_count=20,
            trigger_interval_pct="4",
            divisions=25,
            initial_entry="moc",
        )

        result = _run_strategy_random_payload(payload)

        self.assertEqual(result["result_type"], "strategy_random_comparison")
        self.assertEqual(len(result["summary"]), 6)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["config"]["v4_split_count"], 20)
        self.assertEqual(result["config"]["trigger_interval_pct"], 4.0)
        self.assertEqual(result["config"]["divisions"], 25)
        self.assertTrue(result["methodology"]["same_period_for_all_strategies"])

    def test_strategy_random_payload_supports_uniform_fixed_length_starts(self) -> None:
        result = _run_strategy_random_payload(dict(
            self.payload,
            count=50,
            min_days=2,
            max_days=6,
            seed=77,
            uniform_start_sampling=True,
            initial_entry="moc",
        ))

        self.assertEqual(result["config"]["requested_count"], 50)
        self.assertEqual(result["config"]["count"], 5)
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual({row["trading_days"] for row in result["rows"]}, {2})
        self.assertEqual(result["rows"][0]["start_date"], "2024-01-01")
        self.assertEqual(result["rows"][-1]["start_date"], "2024-01-05")
        self.assertTrue(result["methodology"]["sample_count_capped"])

    def test_lth_random_payload_supports_uniform_fixed_length_starts(self) -> None:
        result = _run_random_payload({
            "analysis_mode": "lth_v4",
            "symbols": ["TQQQ", "SOXL"],
            "splits": [20],
            "principal": "20000",
            "start_date": "2024-01-01",
            "end_date": "2024-01-08",
            "count": 50,
            "min_days": 2,
            "max_days": 1,
            "seed": 77,
            "uniform_start_sampling": True,
            "csv_dir": str(self.qld.parent),
        })

        self.assertEqual(result["result_type"], "lth_random_comparison")
        self.assertEqual(result["config"]["requested_count"], 50)
        self.assertEqual(result["config"]["count"], 5)
        self.assertEqual(len(result["sample_rows"]), 5)
        self.assertEqual({row["trading_days"] for row in result["sample_rows"]}, {2})
        self.assertTrue(result["methodology"]["strict_common_dates"])

    def test_background_random_job_exposes_progress_and_result(self) -> None:
        payload = dict(self.payload, count=4, min_days=2, max_days=4, seed=19, initial_entry="moc")

        started = _start_random_job(payload)
        snapshot = started
        deadline = time.monotonic() + 3
        while snapshot["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = _random_job_snapshot(started["job_id"])

        self.assertEqual(snapshot["status"], "completed", snapshot.get("error"))
        self.assertEqual(snapshot["completed"], 4)
        self.assertEqual(snapshot["total"], 4)
        self.assertEqual(snapshot["progress_pct"], 100.0)
        self.assertEqual(snapshot["result"]["result_type"], "strategy_random_comparison")
        self.assertEqual(len(snapshot["result"]["rows"]), 4)

    def test_background_random_job_rejects_more_than_five_thousand_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "1~5,000"):
            _start_random_job(dict(self.payload, count=5001))

    def test_mixed_price_basis_is_rejected(self) -> None:
        text = self.soxl.read_text(encoding="utf-8").replace("actual_split_adjusted", "user_provided")
        self.soxl.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "가격 기준"):
            _run_payload(self.payload)


if __name__ == "__main__":
    unittest.main()
