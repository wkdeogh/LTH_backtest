from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.engine import Simulator, apply_t_effect, calculate_star_percent, run_backtest
from lth_backtest.models import BacktestConfig, PriceBar
from lth_backtest.precision import round_money, round_order_price, round_rate


D = Decimal


def bar(date: str, *, open: str = "100", high: str = "100", low: str = "100", close: str = "100") -> PriceBar:
    return PriceBar(date, D(open), D(high), D(low), D(close), D(close), 1_000_000)


class FormulaTests(unittest.TestCase):
    def test_official_star_formulas(self) -> None:
        self.assertEqual(calculate_star_percent(BacktestConfig("TQQQ", 20, D("20000")), D("8")), D("0.03"))
        self.assertEqual(calculate_star_percent(BacktestConfig("TQQQ", 40, D("20000")), D("8")), D("0.09"))
        self.assertEqual(calculate_star_percent(BacktestConfig("SOXL", 20, D("20000")), D("8.6")), D("0.028"))
        self.assertEqual(calculate_star_percent(BacktestConfig("SOXL", 40, D("20000")), D("8")), D("0.12"))

    def test_t_effects_match_document(self) -> None:
        self.assertEqual(apply_t_effect(D("7"), "buy_full", 20), D("8.0000000000"))
        self.assertEqual(apply_t_effect(D("7"), "buy_half", 20), D("7.5000000000"))
        self.assertEqual(apply_t_effect(D("7"), "quarter_sell", 20), D("5.2500000000"))
        self.assertEqual(apply_t_effect(D("7"), "limit_sell", 20), D("1.7500000000"))
        self.assertEqual(apply_t_effect(D("39.5"), "reverse_sell", 40), D("37.5250000000"))
        self.assertEqual(apply_t_effect(D("37.525"), "reverse_buy", 40), D("38.1437500000"))

    def test_rounding_is_half_up_not_bankers_rounding(self) -> None:
        self.assertEqual(round_order_price(D("1.005")), D("1.01"))
        self.assertEqual(round_money(D("500.5641025641")), D("500.5641"))
        self.assertEqual(round_rate(D("1E+40")), D("10000000000000000000000000000000000000000.00000000"))


class FillModelTests(unittest.TestCase):
    def test_equity_curve_preserves_ohlcv_for_candlestick_chart(self) -> None:
        prices = [
            PriceBar("2024-01-02", D("98.5"), D("105.25"), D("97.75"), D("102.125"), D("102.125"), 1_234_567),
            bar("2024-01-03", open="102", high="106", low="101", close="104"),
        ]

        point = run_backtest(BacktestConfig("TQQQ", 40, D("20000")), prices).equity_curve[0]

        self.assertEqual(point["open"], D("98.5"))
        self.assertEqual(point["high"], D("105.25"))
        self.assertEqual(point["low"], D("97.75"))
        self.assertEqual(point["close"], D("102.125"))
        self.assertEqual(point["volume"], 1_234_567)

    def test_intraday_high_fills_final_limit_when_close_does_not(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="100", high="115", low="85", close="90"),
        ]
        intraday = run_backtest(BacktestConfig("TQQQ", 40, D("20000"), fill_model="intraday_high"), prices)
        close_only = run_backtest(BacktestConfig("TQQQ", 40, D("20000"), fill_model="close_only"), prices)

        high_fills = [item for item in intraday.executions if item.order_type == "LIMIT"]
        close_fills = [item for item in close_only.executions if item.order_type == "LIMIT"]
        self.assertEqual(len(high_fills), 1)
        self.assertEqual(len(close_fills), 0)
        self.assertTrue(high_fills[0].intraday_triggered)
        self.assertEqual(high_fills[0].fill_price, D("115.00"))
        self.assertEqual(intraday.diagnostics["intraday_high_only_fills"], 1)
        self.assertNotEqual(intraday.summary["ending_equity"], close_only.summary["ending_equity"])

    def test_limit_sell_then_two_half_buys_uses_combined_t_formula(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="100", high="115", low="85", close="90"),
        ]
        result = run_backtest(BacktestConfig("TQQQ", 40, D("20000")), prices)
        day_two = [item for item in result.executions if item.date == "2024-01-03"]
        self.assertEqual([item.order_type for item in day_two], ["LIMIT", "LOC", "LOC"])
        self.assertEqual(result.state["t_value"], D("1.2500000000"))
        self.assertEqual(result.state["position_qty"], 5)

    def test_loc_buy_uses_close_not_intraday_low_or_high(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="110", high="120", low="90", close="116"),
        ]
        result = run_backtest(BacktestConfig("TQQQ", 40, D("20000")), prices)
        buys_on_second_day = [item for item in result.executions if item.date == "2024-01-03" and item.side == "buy"]
        self.assertEqual(buys_on_second_day, [])

    def test_full_round_closes_only_when_reserved_limit_and_quarter_orders_both_fill(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="100", high="116", low="100", close="115"),
            bar("2024-01-04", open="115", high="116", low="114", close="115"),
        ]
        result = run_backtest(BacktestConfig("TQQQ", 40, D("20000")), prices)
        self.assertEqual(len(result.rounds), 1)
        self.assertEqual(result.rounds[0].ended_at, "2024-01-03")
        self.assertEqual(result.rounds[0].ending_equity, D("20075.0000"))
        self.assertEqual(result.state["round_number"], 2)

    def test_completed_round_includes_its_own_close_mdd_and_dates(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="80", high="80", low="80", close="80"),
            bar("2024-01-04", open="115", high="120", low="115", close="115"),
        ]

        result = run_backtest(BacktestConfig("TQQQ", 40, D("20000")), prices)
        completed_round = result.rounds[0]

        self.assertEqual(completed_round.close_mdd, D("-0.50000000"))
        self.assertEqual(completed_round.benchmark_profit_rate, D("15.00000000"))
        self.assertEqual(completed_round.mdd_peak_date, "2024-01-02")
        self.assertEqual(completed_round.mdd_trough_date, "2024-01-03")
        self.assertEqual(completed_round.close_mdd, result.metrics["close_mdd"])


class ReverseModeTests(unittest.TestCase):
    def test_reverse_can_return_to_normal_after_first_day_close(self) -> None:
        day = bar("2024-01-08", open="88", high="92", low="87", close="90")
        simulator = Simulator(BacktestConfig("TQQQ", 40, D("20000")), [bar("2024-01-05"), day])
        simulator.state.cash_balance = D("0")
        simulator.state.position_qty = 200
        simulator.state.avg_price = D("100")
        simulator.state.t_value = D("39.5")
        simulator.state.mode = "reverse"
        simulator.state.round_started_at = "2023-12-01"
        simulator._process_reverse_day(day, [D("80"), D("81"), D("82"), D("83"), D("84")])
        self.assertEqual(simulator.state.position_qty, 190)
        self.assertEqual(simulator.state.t_value, D("37.5250000000"))
        self.assertEqual(simulator.state.mode, "normal")
        self.assertEqual(simulator.diagnostics["reverse_returns"], 1)


class CostTests(unittest.TestCase):
    def test_commission_and_sell_fee_reduce_cash_and_are_reported(self) -> None:
        prices = [
            bar("2024-01-02"),
            bar("2024-01-03", open="100", high="116", low="100", close="115"),
        ]
        result = run_backtest(BacktestConfig(
            "TQQQ", 40, D("20000"), commission=D("1"), sell_fee_bps=D("10")
        ), prices)
        self.assertGreater(result.metrics["total_fees"], D("3"))
        self.assertLess(result.summary["ending_equity"], D("20150"))


if __name__ == "__main__":
    unittest.main()
