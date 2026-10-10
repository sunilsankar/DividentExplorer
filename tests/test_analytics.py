from datetime import date
import unittest

from app.analytics.calculations import calculate_dividend_metrics
from app.db.models import DividendEvent, FinancialMetric


class TestAnalyticsCalculations(unittest.TestCase):
    def test_empty_events(self):
        res = calculate_dividend_metrics(events=[])
        self.assertIsNone(res.current_yield)
        self.assertIsNone(res.annual_dividend)
        self.assertEqual(res.years_paying, 0)
        self.assertEqual(res.years_growing, 0)
        self.assertIsNone(res.quality_score)

    def test_basic_dividend_metrics(self):
        as_of_date = date(2026, 6, 1)
        events = [
            # 2026 payments
            DividendEvent(ex_date=date(2026, 3, 1), amount=1.0, status="ACTUAL"),
            # 2025 payments
            DividendEvent(ex_date=date(2025, 12, 1), amount=1.0, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 9, 1), amount=1.0, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 6, 1), amount=1.0, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 3, 1), amount=0.9, status="ACTUAL"),
            # 2024 payments
            DividendEvent(ex_date=date(2024, 12, 1), amount=0.9, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 9, 1), amount=0.9, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 6, 1), amount=0.9, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 3, 1), amount=0.8, status="ACTUAL"),
        ]

        fin = FinancialMetric(
            pe_ratio=20.0,
            market_cap=1000000.0,
            free_cash_flow=50000.0,
            debt_to_equity=0.5,
        )

        res = calculate_dividend_metrics(
            events=events,
            latest_price=100.0,
            financial=fin,
            as_of=as_of_date,
        )

        # 4 payments in the trailing 365 days: 1.0 + 1.0 + 1.0 + 1.0 = 4.0
        self.assertEqual(res.annual_dividend, 4.0)
        # Yield: 4.0 / 100.0 = 0.04 (4%)
        self.assertEqual(res.current_yield, 0.04)
        self.assertEqual(res.trailing_yield, 0.04)
        # Forward yield: 1.0 * 4 / 100.0 = 0.04
        self.assertEqual(res.forward_yield, 0.04)

        # Years paying: 2026, 2025, 2024 -> 3 years
        self.assertGreaterEqual(res.years_paying, 2)
        # Quality score should be computed
        self.assertIsNotNone(res.quality_score)
        self.assertGreater(res.quality_score, 0)
        self.assertLessEqual(res.quality_score, 100)

    def test_semiannual_frequency_and_forward_yield(self):
        # Model Toyo Tires (TYR.F): semiannual payments (June and December)
        as_of = date(2026, 10, 1)
        events = [
            DividendEvent(ex_date=date(2026, 6, 27), amount=0.39, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 12, 28), amount=0.28, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 6, 26), amount=0.33, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 12, 27), amount=0.25, status="ACTUAL"),
        ]
        res = calculate_dividend_metrics(
            events=events,
            latest_price=20.0,
            as_of=as_of,
        )
        # Trailing 12 months has 2 payments: 0.39 + 0.28 = 0.67
        self.assertEqual(res.annual_dividend, 0.67)
        # Forward dividend should use semiannual multiplier (2 * 0.39 = 0.78), NOT quarterly (4 * 0.39 = 1.56)
        # Forward yield: 0.78 / 20.0 = 0.039 (3.90%)
        self.assertAlmostEqual(res.forward_yield, 0.039, places=3)

    def test_fcf_coverage_calculation(self):
        # 117.2M EUR estimated payout, 202.1M EUR FCF -> ~1.72x coverage
        events = [
            DividendEvent(ex_date=date(2025, 12, 1), amount=0.39, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 6, 1), amount=0.28, status="ACTUAL"),
        ]
        fin = FinancialMetric(
            market_cap=3500000000.0,
            free_cash_flow=202000000.0,
        )
        res = calculate_dividend_metrics(
            events=events,
            latest_price=20.0,
            financial=fin,
            as_of=date(2026, 1, 1),
        )
        # Annual div: 0.67, price: 20.0 -> div yield: 0.0335
        # Total payout: 0.0335 * 3.5B = 117.25M
        # Coverage: 202M / 117.25M ≈ 1.72x
        self.assertIsNotNone(res.fcf_coverage)
        self.assertAlmostEqual(res.fcf_coverage, 1.72, places=1)

    def test_three_year_dividend_cagr(self):
        # 2022: 0.40, 2023: 0.48, 2024: 0.58, 2025: 0.67
        # 3Y CAGR from 2022 to 2025: (0.67 / 0.40) ** (1/3) - 1 ≈ 18.76%
        events = [
            DividendEvent(ex_date=date(2025, 12, 1), amount=0.35, status="ACTUAL"),
            DividendEvent(ex_date=date(2025, 6, 1), amount=0.32, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 12, 1), amount=0.30, status="ACTUAL"),
            DividendEvent(ex_date=date(2024, 6, 1), amount=0.28, status="ACTUAL"),
            DividendEvent(ex_date=date(2023, 12, 1), amount=0.25, status="ACTUAL"),
            DividendEvent(ex_date=date(2023, 6, 1), amount=0.23, status="ACTUAL"),
            DividendEvent(ex_date=date(2022, 12, 1), amount=0.21, status="ACTUAL"),
            DividendEvent(ex_date=date(2022, 6, 1), amount=0.19, status="ACTUAL"),
        ]
        res = calculate_dividend_metrics(
            events=events,
            latest_price=20.0,
            as_of=date(2026, 1, 1),
        )
        self.assertIsNotNone(res.growth_3y)
        self.assertAlmostEqual(res.growth_3y, 0.1876, places=2)

    def test_missing_data_cannot_earn_full_marks(self):
        # 25 years paying, high yield, high growth, but NO financial data
        events = [
            DividendEvent(ex_date=date(2026 - i, 6, 1), amount=2.0 + i * 0.1, status="ACTUAL")
            for i in range(26)
        ]
        res = calculate_dividend_metrics(
            events=events,
            latest_price=50.0,
            financial=None, # Missing financial data
            as_of=date(2026, 6, 1),
        )
        self.assertIsNotNone(res.quality_score)
        self.assertLessEqual(res.quality_score, 85.0)


if __name__ == "__main__":
    unittest.main()
