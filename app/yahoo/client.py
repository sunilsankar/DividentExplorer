from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
import time
from typing import Any, Dict, List, Optional
import yfinance as yf


class UpstreamThrottledError(Exception):
    """Raised when upstream API throttles or returns 429."""
    def __init__(self, message: str = "Rate limited by upstream provider", pause_seconds: float = 60.0) -> None:
        super().__init__(message)
        self.pause_seconds = pause_seconds


class YahooProviderError(Exception):
    """Raised on upstream errors that are not rate limits."""
    pass


def clean_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def clean_int(val: Any) -> Optional[int]:
    f = clean_float(val)
    return int(f) if f is not None else None


def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


@dataclass(frozen=True)
class DiscoveredTicker:
    ticker: str
    name: str
    exchange: str
    asset_type: str = "STOCK"


@dataclass(frozen=True)
class CompanyProfileData:
    ticker: str
    name: str
    exchange_code: str
    sector: Optional[str]
    industry: Optional[str]
    country: Optional[str]
    currency: Optional[str]
    asset_type: str = "STOCK"


@dataclass(frozen=True)
class DividendEventData:
    ex_date: Optional[date]
    pay_date: Optional[date]
    amount: Optional[float]
    currency: Optional[str] = None
    frequency: Optional[str] = None
    status: str = "ACTUAL"


@dataclass(frozen=True)
class PriceHistoryData:
    date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    adj_close: Optional[float]
    volume: Optional[int]


@dataclass(frozen=True)
class FinancialData:
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    pb_ratio: Optional[float]
    debt_to_equity: Optional[float]
    roe: Optional[float]
    roa: Optional[float]
    earnings_growth: Optional[float]
    revenue_growth: Optional[float]
    free_cash_flow: Optional[float]
    operating_cash_flow: Optional[float]


# ponytail: curated seed tickers fallback; ceiling is static list when screener fails, upgrade to SEC EDGAR / exchange bulk files if full market discovery needed
DEFAULT_EXCHANGE_TICKERS: Dict[str, List[DiscoveredTicker]] = {
    "NYSE": [
        DiscoveredTicker("JNJ", "Johnson & Johnson", "NYSE"),
        DiscoveredTicker("PG", "Procter & Gamble Co.", "NYSE"),
        DiscoveredTicker("KO", "Coca-Cola Co.", "NYSE"),
        DiscoveredTicker("XOM", "Exxon Mobil Corp.", "NYSE"),
        DiscoveredTicker("CVX", "Chevron Corp.", "NYSE"),
        DiscoveredTicker("ABBV", "AbbVie Inc.", "NYSE"),
        DiscoveredTicker("MCD", "McDonald's Corp.", "NYSE"),
        DiscoveredTicker("T", "AT&T Inc.", "NYSE"),
        DiscoveredTicker("VZ", "Verizon Communications Inc.", "NYSE"),
        DiscoveredTicker("IBM", "International Business Machines Corp.", "NYSE"),
        DiscoveredTicker("JPM", "JPMorgan Chase & Co.", "NYSE"),
        DiscoveredTicker("O", "Realty Income Corp.", "NYSE"),
        DiscoveredTicker("NEE", "NextEra Energy Inc.", "NYSE"),
        DiscoveredTicker("DUK", "Duke Energy Corp.", "NYSE"),
        DiscoveredTicker("SO", "Southern Co.", "NYSE"),
        DiscoveredTicker("MMM", "3M Co.", "NYSE"),
    ],
    "NASDAQ": [
        DiscoveredTicker("MSFT", "Microsoft Corp.", "NASDAQ"),
        DiscoveredTicker("AAPL", "Apple Inc.", "NASDAQ"),
        DiscoveredTicker("CSCO", "Cisco Systems Inc.", "NASDAQ"),
        DiscoveredTicker("TXN", "Texas Instruments Inc.", "NASDAQ"),
        DiscoveredTicker("AVGO", "Broadcom Inc.", "NASDAQ"),
        DiscoveredTicker("PEP", "PepsiCo Inc.", "NASDAQ"),
        DiscoveredTicker("INTC", "Intel Corp.", "NASDAQ"),
        DiscoveredTicker("QCOM", "QUALCOMM Inc.", "NASDAQ"),
        DiscoveredTicker("AMAT", "Applied Materials Inc.", "NASDAQ"),
        DiscoveredTicker("GILD", "Gilead Sciences Inc.", "NASDAQ"),
        DiscoveredTicker("CMCSA", "Comcast Corp.", "NASDAQ"),
        DiscoveredTicker("FAST", "Fastenal Co.", "NASDAQ"),
        DiscoveredTicker("PAYX", "Paychex Inc.", "NASDAQ"),
        DiscoveredTicker("ADP", "Automatic Data Processing Inc.", "NASDAQ"),
    ],
    "AMS": [
        DiscoveredTicker("ASML.AS", "ASML Holding N.V.", "AMS"),
        DiscoveredTicker("INGA.AS", "ING Groep N.V.", "AMS"),
        DiscoveredTicker("UNA.AS", "Unilever PLC", "AMS"),
        DiscoveredTicker("HEIA.AS", "Heineken N.V.", "AMS"),
    ],
    "PAR": [
        DiscoveredTicker("MC.PA", "LVMH Moët Hennessy Louis Vuitton", "PAR"),
        DiscoveredTicker("OR.PA", "L'Oréal S.A.", "PAR"),
        DiscoveredTicker("TTE.PA", "TotalEnergies SE", "PAR"),
        DiscoveredTicker("SAN.PA", "Sanofi", "PAR"),
        DiscoveredTicker("AIR.PA", "Airbus SE", "PAR"),
    ],
    "FRA": [
        DiscoveredTicker("SAP.DE", "SAP SE", "FRA"),
        DiscoveredTicker("SIE.DE", "Siemens AG", "FRA"),
        DiscoveredTicker("ALV.DE", "Allianz SE", "FRA"),
        DiscoveredTicker("BAS.DE", "BASF SE", "FRA"),
        DiscoveredTicker("DTE.DE", "Deutsche Telekom AG", "FRA"),
    ],
    "BIT": [
        DiscoveredTicker("ENEL.MI", "Enel S.p.A.", "BIT"),
        DiscoveredTicker("ISP.MI", "Intesa Sanpaolo S.p.A.", "BIT"),
        DiscoveredTicker("ENI.MI", "Eni S.p.A.", "BIT"),
        DiscoveredTicker("G.MI", "Assicurazioni Generali S.p.A.", "BIT"),
    ],
    "LSE": [
        DiscoveredTicker("SHEL.L", "Shell plc", "LSE"),
        DiscoveredTicker("AZN.L", "AstraZeneca PLC", "LSE"),
        DiscoveredTicker("ULVR.L", "Unilever PLC", "LSE"),
        DiscoveredTicker("HSBA.L", "HSBC Holdings plc", "LSE"),
        DiscoveredTicker("BP.L", "BP p.l.c.", "LSE"),
        DiscoveredTicker("GSK.L", "GSK plc", "LSE"),
    ],
    "ARCA": [
        DiscoveredTicker("SCHD", "Schwab U.S. Dividend Equity ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("VYM", "Vanguard High Dividend Yield ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("VIG", "Vanguard Dividend Appreciation ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("DGRO", "iShares Core Dividend Growth ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("HDV", "iShares Core High Dividend ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("SPYD", "SPDR S&P Dividend ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("DVY", "iShares Select Dividend ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("SDY", "SPDR S&P Dividend ETF", "ARCA", asset_type="ETF"),
        DiscoveredTicker("NOBL", "ProShares S&P 500 Dividend Aristocrats ETF", "ARCA", asset_type="ETF"),
    ],
}


# ponytail: mapping from app exchange code to Yahoo screener exchange codes; ceiling is manual dict, upgrade to config or DB if dynamically registered exchanges needed
EXCHANGE_SCREENER_CODES: Dict[str, List[str]] = {
    "NYSE": ["NYQ", "ASE"],
    "NASDAQ": ["NMS", "NGM", "NCM"],
    "ARCA": ["PCX"],
    "AMS": ["AMS"],
    "PAR": ["PAR", "ENX"],
    "FRA": ["FRA", "GER"],
    "BIT": ["MIL"],
    "LSE": ["LSE", "IOB"],
}


class YahooClient:
    """Minimal yfinance wrapper with caching and rate limit / throttling detection."""

    def __init__(self, cache_ttl_seconds: int = 3600) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        # In-memory TTL cache: key -> (timestamp, data)
        self._cache: Dict[str, tuple[float, Any]] = {}

    def _get_cached(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, val = self._cache[key]
            if (time.time() - ts) < self.cache_ttl_seconds:
                return val
            del self._cache[key]
        return None

    def _set_cached(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time(), val)

    def _check_error(self, err: Exception) -> None:
        msg = str(err).lower()
        if "429" in msg or "too many requests" in msg or "rate limit" in msg:
            raise UpstreamThrottledError(f"Yahoo Finance rate limit hit: {err}")
        raise YahooProviderError(f"Yahoo Finance error: {err}") from err

    def _fetch_screen_results(
        self,
        query: Any,
        exchange_code: str,
        seen: set[str],
        out_results: List[DiscoveredTicker],
        rate_limiter: Optional[Any] = None,
        default_asset_type: str = "STOCK",
    ) -> None:
        offset = 0
        while True:
            if offset > 0 and rate_limiter:
                rate_limiter.wait()
            try:
                res = yf.screen(query, size=250, offset=offset)
            except Exception as e:
                self._check_error(e)
                break

            quotes = res.get("quotes", []) if isinstance(res, dict) else []
            if not quotes:
                break

            for item in quotes:
                sym = (item.get("symbol") or "").strip().upper()
                if not sym or sym in seen:
                    continue
                quote_type = (item.get("quoteType") or "").upper()
                asset_type = "ETF" if (default_asset_type == "ETF" or quote_type in ("ETF", "MUTUALFUND")) else "STOCK"

                # ponytail: screener ETFQuery lacks dividend yield filter; filter payload so only dividend-paying ETFs are enqueued. Upgrade to full profile check if screener yield is omitted for newly-paying ETFs
                if asset_type == "ETF":
                    div_y = (
                        item.get("trailingAnnualDividendYield")
                        or item.get("dividendYield")
                        or item.get("trailingAnnualDividendRate")
                        or 0.0
                    )
                    if not (div_y and div_y > 0):
                        continue

                seen.add(sym)
                name = item.get("shortName") or item.get("longName") or sym
                out_results.append(DiscoveredTicker(ticker=sym, name=name, exchange=exchange_code, asset_type=asset_type))

            if len(quotes) < 250 or (isinstance(res, dict) and offset + len(quotes) >= res.get("total", 0)):
                break
            offset += len(quotes)

    def discover_tickers(self, exchange_code: str, rate_limiter: Optional[Any] = None) -> List[DiscoveredTicker]:
        code = exchange_code.upper()
        cache_key = f"discover:{code}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        results: List[DiscoveredTicker] = []
        seen: set[str] = set()

        # Try live yfinance screener discovery
        yf_codes = EXCHANGE_SCREENER_CODES.get(code, [code])
        try:
            from yfinance import ETFQuery, EquityQuery

            # 1. Dividend-paying equities
            q_eq = EquityQuery("and", [
                EquityQuery("is-in", ["exchange", *yf_codes]),
                EquityQuery("gt", ["dividendyield", 0]),
            ])
            self._fetch_screen_results(q_eq, code, seen, results, rate_limiter)

            # 2. ETFs (no dividendyield filter on ETFQuery)
            q_etf = ETFQuery("is-in", ["exchange", *yf_codes])
            self._fetch_screen_results(q_etf, code, seen, results, rate_limiter, default_asset_type="ETF")
        except UpstreamThrottledError:
            raise
        except Exception:
            # ponytail: screener failure falls back to curated static list; ceiling is static list, upgrade to error alerting if monitoring needed
            pass

        # Fallback to curated seed list if screener yielded no results
        if not results:
            for t in DEFAULT_EXCHANGE_TICKERS.get(code, []):
                sym = t.ticker.strip().upper()
                if sym not in seen:
                    seen.add(sym)
                    results.append(t)

        self._set_cached(cache_key, results)
        return results

    def get_company_profile(self, ticker: str) -> Optional[CompanyProfileData]:
        sym = ticker.upper().strip()
        cache_key = f"profile:{sym}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            t = yf.Ticker(sym)
            info = t.get_info()
            if not info or not isinstance(info, dict):
                return None

            name = clean_str(info.get("longName") or info.get("shortName") or sym) or sym
            exchange = clean_str(info.get("exchange") or "UNKNOWN") or "UNKNOWN"
            sector = clean_str(info.get("sector"))
            industry = clean_str(info.get("industry"))
            country = clean_str(info.get("country"))
            currency = clean_str(info.get("currency"))
            quote_type = clean_str(info.get("quoteType"))
            asset_type = "ETF" if quote_type in ("ETF", "MUTUALFUND") else "STOCK"

            profile = CompanyProfileData(
                ticker=sym,
                name=name,
                exchange_code=exchange,
                sector=sector,
                industry=industry,
                country=country,
                currency=currency,
                asset_type=asset_type,
            )
            self._set_cached(cache_key, profile)
            return profile
        except Exception as e:
            self._check_error(e)
            return None

    def get_dividends(self, ticker: str) -> List[DividendEventData]:
        sym = ticker.upper().strip()
        cache_key = f"dividends:{sym}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        events: List[DividendEventData] = []
        try:
            t = yf.Ticker(sym)
            # Lightweight dividends series (Date index -> float amount)
            div_series = t.dividends
            if div_series is not None and not div_series.empty:
                # Infer frequency from event counts in latest active year
                by_yr: dict[int, int] = {}
                for idx in div_series.index:
                    d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                    by_yr[d.year] = by_yr.get(d.year, 0) + 1
                # Infer frequency from event counts in latest completed year
                completed_years = [y for y in sorted(by_yr.keys()) if y < date.today().year]
                ref_year = completed_years[-1] if completed_years else (max(by_yr.keys()) if by_yr else None)
                cnt = by_yr[ref_year] if ref_year else 0
                freq_name = "Annual" if cnt == 1 else "Semiannual" if cnt == 2 else "Monthly" if cnt >= 10 else "Quarterly"

                for idx, amount in div_series.items():
                    amt = clean_float(amount)
                    if amt is None or amt <= 0:
                        continue
                    # Extract date from pandas Timestamp
                    if hasattr(idx, "date"):
                        ex_d = idx.date()
                    elif isinstance(idx, str):
                        ex_d = date.fromisoformat(idx[:10])
                    else:
                        continue

                    events.append(
                        DividendEventData(
                            ex_date=ex_d,
                            pay_date=None,  # Missing source data must remain None
                            amount=amt,
                            frequency=freq_name,
                            status="ACTUAL",
                        )
                    )

            # Check calendar for upcoming/announced dividend if available
            try:
                cal = t.calendar
                if cal and isinstance(cal, dict):
                    ex_date_val = cal.get("Dividend Date") or cal.get("Ex-Dividend Date")
                    if ex_date_val:
                        if hasattr(ex_date_val, "date"):
                            cal_d = ex_date_val.date()
                        elif isinstance(ex_date_val, str):
                            cal_d = date.fromisoformat(ex_date_val[:10])
                        else:
                            cal_d = None

                        if cal_d and cal_d >= date.today():
                            # Only add if not already in events
                            if not any(e.ex_date == cal_d for e in events):
                                events.append(
                                    DividendEventData(
                                        ex_date=cal_d,
                                        pay_date=None,
                                        amount=None,
                                        status="EXPECTED",
                                    )
                                )
            except Exception:
                pass  # Calendar is optional and often absent

            self._set_cached(cache_key, events)
            return events
        except Exception as e:
            self._check_error(e)
            return []

    def get_price_history(self, ticker: str, start: Optional[date] = None) -> List[PriceHistoryData]:
        sym = ticker.upper().strip()
        cache_key = f"prices:{sym}:{start.isoformat() if start else 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        prices: List[PriceHistoryData] = []
        try:
            t = yf.Ticker(sym)
            if start:
                df = t.history(start=start.isoformat(), interval="1d", auto_adjust=False)
            else:
                # Default 2 years for history if starting fresh
                df = t.history(period="2y", interval="1d", auto_adjust=False)

            if df is not None and not df.empty:
                for idx, row in df.iterrows():
                    if hasattr(idx, "date"):
                        row_date = idx.date()
                    elif isinstance(idx, str):
                        row_date = date.fromisoformat(idx[:10])
                    else:
                        continue

                    prices.append(
                        PriceHistoryData(
                            date=row_date,
                            open=clean_float(row.get("Open")),
                            high=clean_float(row.get("High")),
                            low=clean_float(row.get("Low")),
                            close=clean_float(row.get("Close")),
                            adj_close=clean_float(row.get("Adj Close") or row.get("Close")),
                            volume=clean_int(row.get("Volume")),
                        )
                    )

            self._set_cached(cache_key, prices)
            return prices
        except Exception as e:
            self._check_error(e)
            return []

    def get_fx_rate(self, from_curr: Optional[str], to_curr: Optional[str]) -> Optional[float]:
        if not from_curr or not to_curr:
            return 1.0
        if from_curr.upper() == to_curr.upper() and from_curr == to_curr:
            return 1.0

        cache_key = f"fx:{from_curr}:{to_curr}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Handle sub-units like GBp (pence) -> 1 GBP = 100 GBp
        mult = 1.0
        base_from = from_curr.upper()
        base_to = to_curr.upper()
        if from_curr == "GBp":
            base_from = "GBP"
            mult /= 100.0
        if to_curr == "GBp":
            base_to = "GBP"
            mult *= 100.0

        if base_from == base_to:
            self._set_cached(cache_key, mult)
            return mult

        try:
            pair = f"{base_from}{base_to}=X"
            t = yf.Ticker(pair)
            rate = None
            if hasattr(t, "fast_info"):
                rate = clean_float(getattr(t.fast_info, "last_price", None))
            if rate is None:
                info = t.get_info() or {}
                rate = clean_float(info.get("previousClose") or info.get("regularMarketPrice"))
            if rate and rate > 0:
                final_rate = rate * mult
                self._set_cached(cache_key, final_rate)
                return final_rate
        except Exception:
            pass

        return None

    def get_financials(self, ticker: str) -> FinancialData:
        sym = ticker.upper().strip()
        cache_key = f"financials:{sym}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            t = yf.Ticker(sym)
            info = t.get_info() or {}

            currency = clean_str(info.get("currency"))
            financial_currency = clean_str(info.get("financialCurrency"))

            raw_fcf = clean_float(info.get("freeCashflow"))
            raw_ocf = clean_float(info.get("operatingCashflow"))

            # ponytail: convert cash flows to trading currency if financial statements report in foreign currency
            fcf = raw_fcf
            ocf = raw_ocf
            if financial_currency and currency and financial_currency.upper() != currency.upper():
                fx_rate = self.get_fx_rate(financial_currency, currency)
                if fx_rate is not None and fx_rate > 0:
                    fcf = clean_float(raw_fcf * fx_rate) if raw_fcf is not None else None
                    ocf = clean_float(raw_ocf * fx_rate) if raw_ocf is not None else None
                else:
                    # Drop mismatched currencies when FX rate is unavailable to avoid unit mismatch errors (e.g. 305x coverage)
                    fcf = None
                    ocf = None

            fin = FinancialData(
                market_cap=clean_float(info.get("marketCap")),
                pe_ratio=clean_float(info.get("trailingPE")),
                forward_pe=clean_float(info.get("forwardPE")),
                pb_ratio=clean_float(info.get("priceToBook")),
                debt_to_equity=clean_float(info.get("debtToEquity")),
                roe=clean_float(info.get("returnOnEquity")),
                roa=clean_float(info.get("returnOnAssets")),
                earnings_growth=clean_float(info.get("earningsGrowth")),
                revenue_growth=clean_float(info.get("revenueGrowth")),
                free_cash_flow=fcf,
                operating_cash_flow=ocf,
            )
            self._set_cached(cache_key, fin)
            return fin
        except Exception as e:
            self._check_error(e)
            return FinancialData(
                market_cap=None,
                pe_ratio=None,
                forward_pe=None,
                pb_ratio=None,
                debt_to_equity=None,
                roe=None,
                roa=None,
                earnings_growth=None,
                revenue_growth=None,
                free_cash_flow=None,
                operating_cash_flow=None,
            )
