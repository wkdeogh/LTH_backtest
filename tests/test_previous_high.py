from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.models import PriceBar
from lth_backtest.previous_high import (
    PreviousHighConfig,
    PreviousHighSimulator,
    run_previous_high_backtest,
)


D = Decimal


def bar(
    date: str,
    *,
    open: str = "100",
    close: str | None = None,
    high: str | None = None,
    low: str | None = None,
) -> PriceBar:
    close_value = D(close if close is not None else open)
    open_value = D(open)
    high_value = D(high) if high is not None else max(open_value, close_value)
    low_value = D(low) if low is not None else min(open_value, close_value)
    return PriceBar(
        date=date,
        open=open_value,
        high=high_value,
        low=low_value,
        close=close_value,
        adj_close=close_value,
        volume=1_000_000,
    )


class PreviousHighInitializationTests(unittest.TestCase):
    def test_price_basis_is_resolved_without_false_actual_price_claim(self) -> None:
        soxx = [bar("2024-01-02"), bar("2024-01-03")]
        soxl = [bar("2024-01-02", open="20"), bar("2024-01-03", open="20")]

        unknown = run_previous_high_backtest(PreviousHighConfig(D("20000")), soxx, soxl)
        actual = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            soxx,
            soxl,
            {"SOXX": {"price_basis": "actual_split_adjusted"}, "SOXL": {"price_basis": "actual_split_adjusted"}},
        )

        self.assertEqual(unknown["config"]["price_basis"], "unknown")
        self.assertIn("실제 거래가격으로 단정하지 않습니다", " ".join(unknown["warnings"]))
        self.assertEqual(actual["config"]["price_basis"], "actual_split_adjusted")
        self.assertIn("분할 반영·배당 미보정 실제 OHLC", " ".join(actual["warnings"]))

    def test_initial_close_buy_sets_peak_equity_and_basis(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20050"), divisions=20),
            [bar("2024-01-02"), bar("2024-01-03")],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="20")],
        )

        self.assertEqual(result["summary"]["soxx_shares"], D("200"))
        self.assertEqual(result["summary"]["cash_balance"], D("50.0000"))
        self.assertEqual(result["state"]["peak_price"], D("100"))
        self.assertEqual(result["state"]["peak_portfolio_value"], D("20050.0000"))
        self.assertEqual(result["state"]["basis_amount"], D("1002.5000"))
        self.assertEqual(result["summary"]["execution_count"], 1)
        self.assertEqual(result["summary"]["order_count"], 1)
        self.assertEqual(result["executions"][0]["action"], "INITIAL_BUY_SOXX")
        self.assertEqual(result["executions"][0]["execution_type"], "close")

    def test_config_rejects_invalid_numeric_ranges(self) -> None:
        invalid = (
            {"principal": D("0")},
            {"principal": D("NaN")},
            {"principal": D("1000"), "trigger_interval_pct": D("0")},
            {"principal": D("1000"), "trigger_interval_pct": D("100")},
            {"principal": D("1000"), "trigger_interval_pct": D("NaN")},
            {"principal": D("1000"), "divisions": 1},
            {"principal": D("1000"), "divisions": 501},
            {"principal": D("1000"), "slippage_bps": D("-1")},
            {"principal": D("1000"), "slippage_bps": D("10000")},
            {"principal": D("1000"), "slippage_bps": D("Infinity")},
            {"principal": D("1000"), "commission": D("-1")},
            {"principal": D("1000"), "commission": D("NaN")},
            {"principal": D("1000"), "sell_fee_bps": D("-1")},
            {"principal": D("1000"), "sell_fee_bps": D("10000")},
            {"principal": D("1000"), "annual_risk_free_rate": D("NaN")},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    PreviousHighConfig(**kwargs)


class PreviousHighExecutionTests(unittest.TestCase):
    def test_full_numeric_round_lifecycle(self) -> None:
        soxx = [
            bar("2024-01-02"),
            bar("2024-01-03", open="96", high="96", low="80", close="94"),
            bar("2024-01-04", open="96", close="96"),
            bar("2024-01-05", open="96", close="94"),
            bar("2024-01-08", open="89", close="89"),
            bar("2024-01-09", open="101", close="101"),
        ]
        soxl = [
            bar("2024-01-02", open="20"),
            bar("2024-01-03", open="20"),
            bar("2024-01-04", open="21"),
            bar("2024-01-05", open="20"),
            bar("2024-01-08", open="18"),
            bar("2024-01-09", open="22"),
        ]

        result = run_previous_high_backtest(PreviousHighConfig(D("20000")), soxx, soxl)
        conversions = [row for row in result["executions"] if row["action"] == "SOXX_TO_SOXL"]
        recovery = [row for row in result["executions"] if row["action"] == "SOXL_TO_SOXX_RECOVERY"]

        self.assertEqual(len(conversions), 2)
        self.assertEqual(conversions[0]["execution_type"], "close")
        self.assertEqual(conversions[0]["trigger_steps"], [1])
        self.assertEqual(conversions[0]["soxx_shares_after"], D("190"))
        self.assertEqual(conversions[0]["soxl_shares_after"], D("47"))
        self.assertEqual(conversions[1]["execution_type"], "open")
        self.assertEqual(conversions[1]["trigger_steps"], [2])
        self.assertEqual(conversions[1]["soxx_shares_after"], D("179"))
        self.assertEqual(conversions[1]["soxl_shares_after"], D("101"))
        self.assertEqual(conversions[1]["cash"], D("7.0000"))
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0]["execution_type"], "open")

        self.assertEqual(result["summary"]["ending_equity"], D("20308.0000"))
        self.assertEqual(result["summary"]["profit_rate"], D("1.54000000"))
        self.assertEqual(result["summary"]["soxx_shares"], D("201"))
        self.assertEqual(result["summary"]["soxl_shares"], D("0"))
        self.assertEqual(result["summary"]["cash_balance"], D("7.0000"))
        self.assertEqual(result["summary"]["execution_count"], 4)
        self.assertEqual(result["summary"]["order_count"], 7)

        completed = result["rounds"][0]
        self.assertEqual(completed["return_pct"], D("1.54000000"))
        self.assertEqual(completed["number_of_conversion_steps"], 2)
        self.assertEqual(completed["conversion_events"], 2)
        self.assertEqual(completed["max_soxx_drawdown"], D("-11.00000000"))
        self.assertEqual(completed["max_portfolio_drawdown"], D("-11.22000000"))
        self.assertEqual(completed["max_soxl_weight"], D("10.23879252"))
        self.assertEqual(completed["max_effective_leverage"], D("1.20438162"))
        self.assertEqual(completed["duration_days"], 7)
        self.assertEqual(completed["duration_trading_days"], 6)
        self.assertEqual(completed["recovery_trading_days"], 5)

    def test_open_gap_executes_all_new_stages_in_one_event(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [bar("2024-01-02"), bar("2024-01-03", open="89", close="92")],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="10", close="11")],
        )

        conversion = result["executions"][1]
        self.assertEqual(conversion["action"], "SOXX_TO_SOXL")
        self.assertEqual(conversion["execution_type"], "open")
        self.assertEqual(conversion["trigger_steps"], [1, 2])
        self.assertEqual(conversion["soxx_gross"], D("1958.0000"))
        self.assertEqual(conversion["soxl_gross"], D("1950.0000"))
        self.assertEqual(result["state"]["soxx_shares"], D("178"))
        self.assertEqual(result["state"]["soxl_shares"], D("195"))
        self.assertEqual(result["state"]["cash"], D("8.0000"))
        self.assertEqual(result["strategy_metrics"]["conversion_event_count"], 1)
        self.assertEqual(result["strategy_metrics"]["recovery_conversion_count"], 0)
        self.assertEqual(result["strategy_metrics"]["total_transfer_event_count"], 1)
        self.assertEqual(result["strategy_metrics"]["executed_step_count"], 2)

    def test_open_and_close_can_execute_different_new_stages(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [bar("2024-01-02"), bar("2024-01-03", open="94", close="89")],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="10", close="9")],
        )

        conversions = [row for row in result["executions"] if row["action"] == "SOXX_TO_SOXL"]
        self.assertEqual([(row["execution_type"], row["trigger_steps"]) for row in conversions], [
            ("open", [1]),
            ("close", [2]),
        ])
        self.assertEqual(result["state"]["soxx_shares"], D("179"))
        self.assertEqual(result["state"]["soxl_shares"], D("202"))
        self.assertEqual(result["state"]["cash"], D("7.0000"))

    def test_open_conversion_snapshot_is_included_in_round_and_strategy_risk_metrics(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("10000"), divisions=20),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="50", high="100", low="50", close="100"),
            ],
            [
                bar("2024-01-02", open="10"),
                bar("2024-01-03", open="5", high="10", low="5", close="10"),
            ],
        )

        completed = result["rounds"][0]
        self.assertEqual(completed["end_phase"], "close")
        self.assertEqual(completed["number_of_conversion_steps"], 10)
        self.assertEqual(completed["max_soxx_drawdown"], D("-50.00000000"))
        self.assertEqual(completed["max_portfolio_drawdown"], D("-50.00000000"))
        self.assertEqual(completed["max_loss_from_start"], D("-50.00000000"))
        self.assertEqual(completed["max_soxl_weight"], D("100.00000000"))
        self.assertEqual(completed["max_effective_leverage"], D("3.00000000"))
        self.assertEqual(result["strategy_metrics"]["max_soxl_weight"], D("100.00000000"))
        self.assertEqual(result["strategy_metrics"]["max_effective_leverage"], D("3.00000000"))

        # Daily close analytics remain close-only even though the intraday
        # exposure snapshots feed the maximum risk statistics above.
        self.assertEqual(result["metrics"]["close_mdd"], D("0E-8"))
        self.assertEqual(result["equity_curve"][-1]["soxl_weight"], D("0E-8"))

    def test_no_trade_open_between_stages_is_included_in_path_risk_metrics(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="100", close="95"),
                bar("2024-01-04", open="93", close="99"),
                bar("2024-01-05", open="100", close="100"),
            ],
            [
                bar("2024-01-02", open="10"),
                bar("2024-01-03", open="10", close="10"),
                bar("2024-01-04", open="10", close="10"),
                bar("2024-01-05", open="12", close="12"),
            ],
        )

        self.assertFalse(any(row["date"] == "2024-01-04" for row in result["executions"]))
        completed = result["rounds"][0]
        self.assertEqual(completed["max_soxx_drawdown"], D("-7.00000000"))
        self.assertEqual(completed["max_portfolio_drawdown"], D("-6.90000000"))
        self.assertEqual(completed["max_loss_from_start"], D("-6.90000000"))
        self.assertEqual(completed["max_soxl_weight"], D("5.10204082"))
        self.assertEqual(completed["max_effective_leverage"], D("1.10204082"))
        self.assertEqual(result["strategy_metrics"]["max_soxl_weight"], D("5.10204082"))
        self.assertEqual(result["strategy_metrics"]["max_effective_leverage"], D("1.10204082"))

    def test_high_and_low_only_touches_never_change_execution(self) -> None:
        ordinary_soxx = [
            bar("2024-01-02"),
            bar("2024-01-03", open="96", close="94"),
            bar("2024-01-04", open="99", close="99"),
        ]
        extreme_soxx = [
            bar("2024-01-02", high="150", low="1"),
            bar("2024-01-03", open="96", high="200", low="1", close="94"),
            bar("2024-01-04", open="99", high="200", low="1", close="99"),
        ]
        soxl = [bar("2024-01-02", open="20"), bar("2024-01-03", open="20"), bar("2024-01-04", open="21")]

        ordinary = run_previous_high_backtest(PreviousHighConfig(D("20000")), ordinary_soxx, soxl)
        extreme = run_previous_high_backtest(PreviousHighConfig(D("20000")), extreme_soxx, soxl)

        self.assertEqual(ordinary["executions"], extreme["executions"])
        self.assertEqual(ordinary["summary"], extreme["summary"])
        self.assertEqual(ordinary["rounds"], extreme["rounds"])
        self.assertEqual(ordinary["strategy_metrics"], extreme["strategy_metrics"])
        self.assertEqual(ordinary["summary"]["completed_rounds"], 0)

    def test_executed_stage_is_not_repeated_after_rebound(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="100", close="94"),
                bar("2024-01-04", open="98", close="98"),
                bar("2024-01-05", open="96", close="94"),
            ],
            [bar(date, open="20") for date in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")],
        )

        conversions = [row for row in result["executions"] if row["action"] == "SOXX_TO_SOXL"]
        self.assertEqual(len(conversions), 1)
        self.assertEqual(conversions[0]["trigger_steps"], [1])
        self.assertEqual(result["state"]["executed_levels"], [1])

    def test_recovery_equality_uses_open_or_close_phase(self) -> None:
        cases = (
            (bar("2024-01-04", open="100", close="100"), "open"),
            (bar("2024-01-04", open="99", close="100"), "close"),
        )
        for recovery_bar, expected_phase in cases:
            with self.subTest(phase=expected_phase):
                result = run_previous_high_backtest(
                    PreviousHighConfig(D("20000")),
                    [bar("2024-01-02"), bar("2024-01-03", open="100", close="94"), recovery_bar],
                    [bar("2024-01-02", open="20"), bar("2024-01-03", open="20"), bar("2024-01-04", open="22")],
                )
                recovery = [row for row in result["executions"] if row["action"] == "SOXL_TO_SOXX_RECOVERY"]
                self.assertEqual(len(recovery), 1)
                self.assertEqual(recovery[0]["execution_type"], expected_phase)
                self.assertEqual(result["rounds"][0]["end_phase"], expected_phase)
                self.assertEqual(result["rounds"][0]["return_pct"], D("0.17000000"))

    def test_open_recovery_precedes_new_close_conversion(self) -> None:
        simulator = PreviousHighSimulator(
            PreviousHighConfig(D("20000")),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="100", close="94"),
                bar("2024-01-04", open="100", close="94"),
            ],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="20"), bar("2024-01-04", open="22", close="20")],
        )
        result = simulator.run()

        same_day = [row for row in result["executions"] if row["date"] == "2024-01-04"]
        self.assertEqual([(row["action"], row["execution_type"]) for row in same_day], [
            ("SOXL_TO_SOXX_RECOVERY", "open"),
            ("SOXX_TO_SOXL", "close"),
        ])
        self.assertEqual(same_day[1]["round_id"], 2)
        self.assertEqual(result["summary"]["completed_rounds"], 1)
        self.assertEqual(result["state"]["round_id"], 2)
        self.assertEqual(result["state"]["executed_levels"], [1])
        self.assertEqual(result["state"]["soxx_shares"], D("190"))
        self.assertEqual(result["state"]["soxl_shares"], D("47"))
        self.assertEqual(result["state"]["cash"], D("34.0000"))
        same_day_path = [
            (point["round_id"], point["phase"])
            for point in simulator.round_path_points
            if point["date"] == "2024-01-04"
        ]
        self.assertIn((1, "open"), same_day_path)
        self.assertIn((2, "open_mark"), same_day_path)

    def test_same_day_open_before_new_close_peak_is_excluded_from_next_round_path(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="120", close="110"),
                bar("2024-01-04", open="104.5", close="104.5"),
                bar("2024-01-05", open="110", close="110"),
            ],
            [
                bar("2024-01-02", open="10"),
                bar("2024-01-03", open="10", close="10"),
                bar("2024-01-04", open="10", close="10"),
                bar("2024-01-05", open="11", close="11"),
            ],
        )

        completed = result["rounds"][0]
        self.assertEqual(completed["start_date"], "2024-01-03")
        self.assertEqual(completed["start_peak"], D("110"))
        self.assertEqual(completed["max_soxx_drawdown"], D("-5.00000000"))
        self.assertEqual(completed["max_portfolio_drawdown"], D("-5.00000000"))

    def test_new_strict_close_high_recalculates_basis_before_next_trigger(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="100", close="110"),
                bar("2024-01-04", open="110", close="104.5"),
            ],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="20"), bar("2024-01-04", open="10")],
        )

        conversion = result["executions"][1]
        self.assertEqual(result["state"]["peak_price"], D("110"))
        self.assertEqual(result["state"]["peak_date"], "2024-01-03")
        self.assertEqual(result["state"]["basis_amount"], D("1100.0000"))
        self.assertEqual(conversion["trigger_level"], D("104.500000"))
        self.assertEqual(conversion["soxx_shares_before"] - conversion["soxx_shares_after"], D("10"))
        self.assertEqual(conversion["soxx_gross"], D("1045.0000"))

    def test_zero_share_stage_remains_pending_then_aggregates_with_next_stage(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("1000"), divisions=20),
            [
                bar("2024-01-02"),
                bar("2024-01-03", open="100", close="95"),
                bar("2024-01-04", open="100", close="90"),
            ],
            [bar("2024-01-02", open="10"), bar("2024-01-03", open="10"), bar("2024-01-04", open="10")],
        )

        conversions = [row for row in result["executions"] if row["action"] == "SOXX_TO_SOXL"]
        self.assertEqual(result["diagnostics"]["zero_share_attempts"], 1)
        self.assertEqual(len(conversions), 1)
        self.assertEqual(conversions[0]["trigger_steps"], [1, 2])
        self.assertEqual(result["state"]["soxx_shares"], D("9"))
        self.assertEqual(result["state"]["soxl_shares"], D("9"))
        self.assertEqual(result["state"]["executed_levels"], [1, 2])

    def test_conversion_is_atomic_when_sale_cannot_buy_one_soxl_share(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("1000"), divisions=10),
            [bar("2024-01-02"), bar("2024-01-03", open="100", close="95")],
            [bar("2024-01-02", open="200"), bar("2024-01-03", open="200")],
        )

        self.assertEqual(result["summary"]["execution_count"], 1)
        self.assertEqual(result["state"]["soxx_shares"], D("10"))
        self.assertEqual(result["state"]["soxl_shares"], D("0"))
        self.assertEqual(result["state"]["cash"], D("0.0000"))
        self.assertEqual(result["state"]["executed_levels"], [])
        self.assertEqual(result["diagnostics"]["zero_share_attempts"], 1)

    def test_conversion_costs_slippage_and_rounding_are_exact(self) -> None:
        config = PreviousHighConfig(
            D("20000"),
            slippage_bps=D("10"),
            commission=D("1"),
            sell_fee_bps=D("10"),
        )
        soxx = [bar("2024-01-02"), bar("2024-01-03", open="100", close="95")]
        soxl = [bar("2024-01-02", open="10"), bar("2024-01-03", open="10")]
        simulator = PreviousHighSimulator(config, soxx, soxl)
        simulator.state.cash = D("0.0000")
        simulator.state.soxx_shares = D("100")
        simulator.state.peak_price = D("100")
        simulator.state.peak_date = "2024-01-02"
        simulator.state.peak_portfolio_value = D("20000")
        simulator.state.basis_amount = D("1000")
        simulator.state.round_anchor_date = "2024-01-02"
        simulator.state.round_anchor_equity = D("20000")

        self.assertTrue(simulator._convert_to_soxl(soxx[1], soxl[1], "close"))
        trade = simulator.trades[0]

        self.assertEqual(trade.soxx_price, D("94.905000"))
        self.assertEqual(trade.soxx_gross, D("949.0500"))
        self.assertEqual(trade.soxl_price, D("10.010000"))
        self.assertEqual(trade.soxl_gross, D("940.9400"))
        self.assertEqual(trade.fees, D("2.9491"))
        self.assertEqual(trade.total_portfolio_value, D("9495.1609"))
        self.assertEqual(simulator.state.soxx_shares, D("90"))
        self.assertEqual(simulator.state.soxl_shares, D("94"))
        self.assertEqual(simulator.state.cash, D("5.1609"))

    def test_recovery_uses_only_soxl_sale_proceeds_and_preserves_existing_cash(self) -> None:
        soxx = [bar("2024-01-02"), bar("2024-01-03", open="100")]
        soxl = [bar("2024-01-02", open="95"), bar("2024-01-03", open="95")]
        simulator = PreviousHighSimulator(PreviousHighConfig(D("1000")), soxx, soxl)
        simulator.state.cash = D("9.0000")
        simulator.state.soxx_shares = D("1")
        simulator.state.soxl_shares = D("1")
        simulator.state.peak_price = D("100")
        simulator.state.peak_date = "2024-01-02"
        simulator.state.basis_amount = D("50")
        simulator.state.round_anchor_date = "2024-01-02"
        simulator.state.round_anchor_equity = D("204")
        simulator.state.first_conversion_date = "2024-01-02"

        self.assertTrue(simulator._recover_to_soxx(soxx[1], soxl[1], "open"))
        self.assertEqual(simulator.state.soxx_shares, D("1"))
        self.assertEqual(simulator.state.soxl_shares, D("0"))
        self.assertEqual(simulator.state.cash, D("104.0000"))
        self.assertEqual(simulator.trades[-1].soxx_gross, D("0.0000"))
        self.assertEqual(simulator.trades[-1].order_count, 1)

    def test_soxx_exhaustion_is_recorded_and_stops_later_conversions(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("1000"), divisions=10),
            [bar("2024-01-02"), bar("2024-01-03", open="50"), bar("2024-01-04", open="40")],
            [bar("2024-01-02", open="10"), bar("2024-01-03", open="10"), bar("2024-01-04", open="10")],
        )

        conversions = [row for row in result["executions"] if row["action"] == "SOXX_TO_SOXL"]
        self.assertEqual(len(conversions), 1)
        self.assertEqual(conversions[0]["trigger_steps"], list(range(1, 6)))
        self.assertEqual(result["state"]["soxx_shares"], D("0"))
        self.assertEqual(result["state"]["soxl_shares"], D("50"))
        self.assertEqual(result["strategy_metrics"]["soxx_exhausted"], True)
        self.assertEqual(result["strategy_metrics"]["first_exhaustion_drawdown"], D("-50.00000000"))
        self.assertEqual(result["strategy_metrics"]["executed_step_count"], 5)
        self.assertEqual(result["strategy_metrics"]["max_reached_stage"], 12)

    def test_active_round_is_included_in_conversion_step_statistics(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("20000")),
            [bar("2024-01-02"), bar("2024-01-03", open="89")],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="18")],
        )

        strategy = result["strategy_metrics"]
        self.assertEqual(strategy["total_rounds"], 0)
        self.assertEqual(strategy["active_round_conversion_steps"], 2)
        self.assertEqual(strategy["conversion_step_round_count"], 1)
        self.assertEqual(strategy["max_conversion_steps_per_round"], 2)
        self.assertEqual(strategy["average_conversion_steps_per_round"], D("2.00000000"))

    def test_fractional_conversion_uses_eight_decimals_and_preserves_phase_value(self) -> None:
        result = run_previous_high_backtest(
            PreviousHighConfig(D("1000"), divisions=10, fractional_shares=True),
            [bar("2024-01-02"), bar("2024-01-03", open="100", close="95")],
            [bar("2024-01-02", open="20"), bar("2024-01-03", open="20")],
        )

        conversion = result["executions"][1]
        self.assertEqual(conversion["soxx_shares_before"] - conversion["soxx_shares_after"], D("1.05263157"))
        self.assertEqual(conversion["soxl_shares_after"], D("5.00000000"))
        self.assertEqual(conversion["soxx_gross"], D("100.0000"))
        self.assertEqual(conversion["soxl_gross"], D("100.0000"))
        self.assertEqual(result["equity_curve"][-1]["equity"], D("950.0000"))
        self.assertGreaterEqual(result["state"]["cash"], D("0"))
        self.assertGreaterEqual(result["state"]["soxx_shares"], D("0"))
        self.assertGreaterEqual(result["state"]["soxl_shares"], D("0"))

    def test_result_is_deterministic_and_future_bars_do_not_change_prefix(self) -> None:
        soxx = [
            bar("2024-01-02"),
            bar("2024-01-03", open="100", close="94"),
            bar("2024-01-04", open="96", close="96"),
            bar("2024-01-05", open="89", close="89"),
            bar("2024-01-08", open="101", close="101"),
        ]
        soxl = [
            bar("2024-01-02", open="20"),
            bar("2024-01-03", open="20"),
            bar("2024-01-04", open="21"),
            bar("2024-01-05", open="18"),
            bar("2024-01-08", open="22"),
        ]
        config = PreviousHighConfig(D("20000"))

        full = run_previous_high_backtest(config, soxx, soxl)
        repeated = run_previous_high_backtest(config, soxx, soxl)
        prefix = run_previous_high_backtest(config, soxx[:4], soxl[:4])

        self.assertEqual(full, repeated)
        self.assertEqual(
            prefix["executions"],
            [row for row in full["executions"] if row["date"] <= "2024-01-05"],
        )
        self.assertEqual(
            prefix["equity_curve"],
            [row for row in full["equity_curve"] if row["date"] <= "2024-01-05"],
        )


if __name__ == "__main__":
    unittest.main()
