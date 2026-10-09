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


if __name__ == "__main__":
    unittest.main()
