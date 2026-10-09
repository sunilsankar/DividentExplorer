from datetime import date
import unittest
from unittest.mock import MagicMock, patch

from app.yahoo.client import (
    CompanyProfileData,
    DEFAULT_EXCHANGE_TICKERS,
    DividendEventData,
    UpstreamThrottledError,
    YahooClient,
    YahooProviderError,
    clean_float,
    clean_int,
    clean_str,
)


class TestYahooClient(unittest.TestCase):
    def test_clean_helpers(self):
        self.assertIsNone(clean_float(None))
        self.assertIsNone(clean_float("not-a-number"))
        self.assertIsNone(clean_float(float("nan")))
        self.assertIsNone(clean_float(float("inf")))
        self.assertEqual(clean_float(12.34), 12.34)
        self.assertEqual(clean_float("45.6"), 45.6)

        self.assertIsNone(clean_int(None))
        self.assertIsNone(clean_int("invalid"))
        self.assertEqual(clean_int(100), 100)
        self.assertEqual(clean_int("500"), 500)

        self.assertIsNone(clean_str(None))
        self.assertIsNone(clean_str("   "))
        self.assertEqual(clean_str("  AAPL  "), "AAPL")

    def test_discover_tickers_curated_fallback(self):
        client = YahooClient()
        nyse = client.discover_tickers("NYSE")
        self.assertTrue(len(nyse) > 0)
        self.assertTrue(any(t.ticker == "JNJ" for t in nyse))

        nasdaq = client.discover_tickers("NASDAQ")
        self.assertTrue(len(nasdaq) > 0)
        self.assertTrue(any(t.ticker == "MSFT" for t in nasdaq))

    def test_client_caching(self):
        client = YahooClient(cache_ttl_seconds=300)
        res1 = client.discover_tickers("NYSE")
        res2 = client.discover_tickers("NYSE")
        self.assertIs(res1, res2)

    @patch("app.yahoo.client.yf.Ticker")
    def test_get_company_profile(self, mock_ticker):
        instance = MagicMock()
        instance.get_info.return_value = {
            "longName": "Johnson & Johnson",
            "exchange": "NYQ",
            "sector": "Healthcare",
            "industry": "Drug Manufacturers",
            "country": "United States",
            "currency": "USD",
        }
        mock_ticker.return_value = instance

        client = YahooClient()
        profile = client.get_company_profile("JNJ")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "Johnson & Johnson")
        self.assertEqual(profile.sector, "Healthcare")
        self.assertEqual(profile.currency, "USD")

    @patch("app.yahoo.client.yf.Ticker")
    def test_throttling_detection(self, mock_ticker):
        instance = MagicMock()
        instance.get_info.side_effect = Exception("429 Too Many Requests")
        mock_ticker.return_value = instance

        client = YahooClient()
        with self.assertRaises(UpstreamThrottledError):
            client.get_company_profile("RATE_LIMITED")

    @patch("app.yahoo.client.yf.Ticker")
    def test_get_dividends_empty(self, mock_ticker):
        instance = MagicMock()
        instance.dividends = None
        instance.calendar = None
        mock_ticker.return_value = instance

        client = YahooClient()
        divs = client.get_dividends("NODIV")
        self.assertEqual(divs, [])


if __name__ == "__main__":
    unittest.main()
