from __future__ import annotations

import unittest
from decimal import Decimal

from lth_backtest.comparison import run_strategy_comparison
from lth_backtest.models import PriceBar
from lth_backtest.previous_high import PreviousHighConfig, run_previous_high_backtest
from lth_backtest.reporting import render_html_report


def bar(date: str, value: str) -> PriceBar:
    price = Decimal(value)
    return PriceBar(date, price, price, price, price, price, 1)


class PreviousHighReportingTests(unittest.TestCase):
    def test_public_previous_high_result_renders_without_comparison_payload(self) -> None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        soxx = [bar(date, price) for date, price in zip(dates, ["100", "94", "101"])]
        soxl = [bar(date, price) for date, price in zip(dates, ["20", "18", "22"])]
        result = run_previous_high_backtest(PreviousHighConfig(Decimal("20000")), soxx, soxl)

        self.assertNotIn("comparison", result)
        report = render_html_report(result)

        self.assertIn("전고점매매법 백테스트", report)
        self.assertIn("전고점매매법 자산곡선", report)
        self.assertIn("SOXL 비중과 실질 레버리지", report)
        self.assertNotIn("4전략 자산곡선", report)
        self.assertIn("table('rounds'", report)
        self.assertIn("가격 기준 unknown", report)
        self.assertNotIn("실제 OHLC 가격수익률", report)

    def test_report_dispatches_to_comparison_layout_and_escapes_warnings(self) -> None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        soxx = [bar(date, price) for date, price in zip(dates, ["100", "94", "101"])]
        soxl = [bar(date, price) for date, price in zip(dates, ["20", "18", "22"])]
        result = run_strategy_comparison(PreviousHighConfig(Decimal("20000")), soxx, soxl)
        result["warnings"].append("<script>alert('x')</script>")

        report = render_html_report(result)

        self.assertIn("전고점매매법 · 4전략 비교", report)
        self.assertIn("SOXX 거치식", report)
        self.assertIn("SOXL 비중과 실질 레버리지", report)
        self.assertIn("&lt;script&gt;alert", report)
        self.assertNotIn("<script>alert('x')</script>", report)
        self.assertIn("table('rounds'", report)

    def test_actual_price_basis_is_only_claimed_when_diagnostics_prove_it(self) -> None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        soxx = [bar(date, price) for date, price in zip(dates, ["100", "94", "101"])]
        soxl = [bar(date, price) for date, price in zip(dates, ["20", "18", "22"])]
        diagnostics = {
            "SOXX": {"price_basis": "actual_split_adjusted"},
            "SOXL": {"price_basis": "actual_split_adjusted"},
        }
        result = run_strategy_comparison(
            PreviousHighConfig(Decimal("20000")), soxx, soxl, data_diagnostics=diagnostics,
        )

        self.assertIn("분할 반영·배당 미보정 실제 OHLC 가격수익률", render_html_report(result))

    def test_six_strategy_report_names_tqqq_and_qld(self) -> None:
        dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
        soxx = [bar(date, price) for date, price in zip(dates, ["100", "94", "101"])]
        soxl = [bar(date, price) for date, price in zip(dates, ["20", "18", "22"])]
        tqqq = [bar(date, price) for date, price in zip(dates, ["40", "37", "43"])]
        qld = [bar(date, price) for date, price in zip(dates, ["30", "29", "32"])]
        result = run_strategy_comparison(
            PreviousHighConfig(Decimal("20000")),
            soxx,
            soxl,
            tqqq_prices=tqqq,
            qld_prices=qld,
        )

        report = render_html_report(result)

        self.assertIn("전고점매매법 · 6전략 비교", report)
        self.assertIn("TQQQ 거치식", report)
        self.assertIn("QLD 거치식", report)
        self.assertIn("6전략 자산곡선", report)


if __name__ == "__main__":
    unittest.main()
