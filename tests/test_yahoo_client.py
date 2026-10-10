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

    @patch("app.yahoo.client.yf.screen")
    def test_discover_tickers_screener(self, mock_screen):
        mock_screen.side_effect = [
            # First call for equities
            {"quotes": [{"symbol": "ASML.AS", "shortName": "ASML Holding", "quoteType": "EQUITY"}], "total": 1},
            # Second call for ETFs: one dividend payer, one non-payer (should be filtered out)
            {"quotes": [
                {"symbol": "ZETH.AS", "shortName": "ZETH ETP", "quoteType": "ETF", "trailingAnnualDividendYield": 0.02},
                {"symbol": "ZERO.AS", "shortName": "Zero Div ETF", "quoteType": "ETF", "trailingAnnualDividendYield": 0.0},
            ], "total": 2},
        ]
        client = YahooClient()
        res = client.discover_tickers("AMS")
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].ticker, "ASML.AS")
        self.assertEqual(res[0].asset_type, "STOCK")
        self.assertEqual(res[1].ticker, "ZETH.AS")
        self.assertEqual(res[1].asset_type, "ETF")

    @patch("app.yahoo.client.yf.screen")
    def test_discover_tickers_curated_fallback_on_error(self, mock_screen):
        mock_screen.side_effect = Exception("Yahoo screener down")
        client = YahooClient()
        nyse = client.discover_tickers("NYSE")
        self.assertTrue(len(nyse) > 0)
        self.assertTrue(any(t.ticker == "JNJ" for t in nyse))

    @patch("app.yahoo.client.yf.screen")
    def test_discover_tickers_pagination_and_rate_limiter(self, mock_screen):
        mock_screen.side_effect = [
            {"quotes": [{"symbol": f"S{i}", "shortName": f"Stock {i}", "quoteType": "EQUITY"} for i in range(250)], "total": 260},
            {"quotes": [{"symbol": f"S{i}", "shortName": f"Stock {i}", "quoteType": "EQUITY"} for i in range(250, 260)], "total": 260},
            {"quotes": [], "total": 0},
        ]
        rate_limiter = MagicMock()
        client = YahooClient()
        res = client.discover_tickers("AMS", rate_limiter=rate_limiter)
        self.assertEqual(len(res), 260)
        rate_limiter.wait.assert_called_once()

    @patch("app.yahoo.client.yf.screen")
    def test_client_caching(self, mock_screen):
        mock_screen.return_value = {"quotes": [], "total": 0}
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

    @patch("app.yahoo.client.yf.Ticker")
    def test_get_financials_currency_conversion(self, mock_ticker):
        instance = MagicMock()
        instance.get_info.return_value = {
            "currency": "EUR",
            "financialCurrency": "JPY",
            "marketCap": 3500000000.0,
            "freeCashflow": 35832373248.0,
            "operatingCashflow": 50000000000.0,
        }
        mock_ticker.return_value = instance

        client = YahooClient()
        # Mock get_fx_rate to return 0.0056395 (1 JPY = 0.0056395 EUR)
        with patch.object(client, "get_fx_rate", return_value=0.0056395):
            fin = client.get_financials("TYR.F")
            self.assertIsNotNone(fin.free_cash_flow)
            # 35.83B JPY * 0.0056395 = ~202,076,668 EUR
            self.assertAlmostEqual(fin.free_cash_flow, 202076668.0, delta=1000.0)

    @patch("app.yahoo.client.yf.Ticker")
    def test_get_financials_unsupported_fx_drops_mismatched_currencies(self, mock_ticker):
        instance = MagicMock()
        instance.get_info.return_value = {
            "currency": "EUR",
            "financialCurrency": "XYZ",
            "marketCap": 1000000.0,
            "freeCashflow": 500000.0,
        }
        mock_ticker.return_value = instance

        client = YahooClient()
        with patch.object(client, "get_fx_rate", return_value=None):
            fin = client.get_financials("UNKNOWN_FX")
            # Dropped to None to prevent 305x unit mismatch corruption
            self.assertIsNone(fin.free_cash_flow)

    def test_discover_tickers_dedups_results(self):
        from app.yahoo.client import DiscoveredTicker
        with patch.dict("app.yahoo.client.DEFAULT_EXCHANGE_TICKERS", {
            "TEST": [
                DiscoveredTicker("T1", "Name 1", "US"),
                DiscoveredTicker("T2", "Name 2", "US"),
                DiscoveredTicker("T1", "Name 1 duplicate", "US"),
            ]
        }):
            client = YahooClient()
            res = client.discover_tickers("TEST")
            self.assertEqual(len(res), 2)
            self.assertEqual([t.ticker for t in res], ["T1", "T2"])


if __name__ == "__main__":
    unittest.main()
