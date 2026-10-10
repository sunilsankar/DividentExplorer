from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from typing import Dict, List, Optional, Sequence

from app.db.models import DividendEvent, FinancialMetric, PriceHistory


@dataclass(frozen=True)
class ComputedDividendMetrics:
    current_yield: Optional[float]
    trailing_yield: Optional[float]
    forward_yield: Optional[float]
    annual_dividend: Optional[float]
    payout_ratio: Optional[float]
    fcf_coverage: Optional[float]
    growth_1y: Optional[float]
    growth_3y: Optional[float]
    growth_5y: Optional[float]
    growth_10y: Optional[float]
    years_paying: Optional[int]
    years_growing: Optional[int]
    quality_score: Optional[float]


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        val = numerator / denominator
        if math.isnan(val) or math.isinf(val):
            return None
        return round(val, 4)
    except Exception:
        return None


def calculate_dividend_metrics(
    events: Sequence[DividendEvent],
    latest_price: Optional[float] = None,
    financial: Optional[FinancialMetric] = None,
    as_of: Optional[date] = None,
) -> ComputedDividendMetrics:
    """Calculate dividend metrics locally from history and prices.
    
    ponytail: pure stdlib math; no numpy/pandas needed for dividend aggregations.
    """
    today = as_of or date.today()

    # Filter valid actual events with a date and positive amount
    valid_events = [
        e for e in events
        if (e.ex_date or e.pay_date) and e.amount is not None and e.amount > 0 and e.status == "ACTUAL"
    ]

    if not valid_events:
        return ComputedDividendMetrics(
            current_yield=None,
            trailing_yield=None,
            forward_yield=None,
            annual_dividend=None,
            payout_ratio=None,
            fcf_coverage=None,
            growth_1y=None,
            growth_3y=None,
            growth_5y=None,
            growth_10y=None,
            years_paying=0,
            years_growing=0,
            quality_score=None,
        )

    # Group by calendar year
    annual_totals: Dict[int, float] = defaultdict(float)
    for e in valid_events:
        event_date = e.ex_date or e.pay_date
        if event_date and event_date <= today:
            annual_totals[event_date.year] += e.amount

    # Trailing 365 days annual dividend
    one_year_ago = today - timedelta(days=365)
    t12m_amount = sum(
        e.amount
        for e in valid_events
        if e.amount and ((e.ex_date and one_year_ago <= e.ex_date <= today) or (not e.ex_date and e.pay_date and one_year_ago <= e.pay_date <= today))
    )

    annual_dividend: Optional[float] = None
    if t12m_amount > 0:
        annual_dividend = round(t12m_amount, 4)
    else:
        # Fallback to most recent completed year if past events exist
        past_years = [y for y in sorted(annual_totals.keys(), reverse=True) if y < today.year]
        if past_years:
            annual_dividend = round(annual_totals[past_years[0]], 4)

    # Yields
    trailing_yield = _safe_div(annual_dividend, latest_price) if latest_price and latest_price > 0 else None
    current_yield = trailing_yield

    # ponytail: infer payment frequency multiplier from trailing 12M or latest year event count; upgrade to calendar recurrence analysis if erratic
    t12m_count = sum(
        1 for e in valid_events
        if ((e.ex_date and one_year_ago <= e.ex_date <= today) or (not e.ex_date and e.pay_date and one_year_ago <= e.pay_date <= today))
    )
    if t12m_count == 0:
        past_years = [y for y in sorted(annual_totals.keys(), reverse=True) if y <= today.year and annual_totals[y] > 0]
        if past_years:
            latest_year = past_years[0]
            t12m_count = sum(1 for e in valid_events if (e.ex_date or e.pay_date).year == latest_year)

    if t12m_count == 1:
        freq_mult = 1.0
    elif t12m_count == 2:
        freq_mult = 2.0
    elif t12m_count >= 10:
        freq_mult = 12.0
    else:
        freq_mult = 4.0  # default quarterly

    # Forward yield: latest payment multiplied by frequency or annual
    sorted_events = sorted(valid_events, key=lambda x: (x.ex_date or x.pay_date or date.min), reverse=True)
    latest_event = sorted_events[0] if sorted_events else None
    forward_dividend = (latest_event.amount * freq_mult) if (latest_event and latest_event.amount) else annual_dividend
    forward_yield = _safe_div(forward_dividend, latest_price) if latest_price and latest_price > 0 else None

    # Years paying (consecutive years with dividends ending at last completed year)
    years_paying = 0
    years_growing = 0
    check_year = today.year if today.year in annual_totals else today.year - 1
    while check_year in annual_totals and annual_totals[check_year] > 0:
        years_paying += 1
        prev_year = check_year - 1
        if prev_year in annual_totals and annual_totals[check_year] >= annual_totals[prev_year]:
            years_growing += 1
        elif prev_year not in annual_totals:
            break
        check_year -= 1

    # Growth CAGR helper
    def cagr(start_val: float, end_val: float, years: int) -> Optional[float]:
        if start_val <= 0 or end_val <= 0 or years <= 0:
            return None
        try:
            rate = (end_val / start_val) ** (1.0 / years) - 1.0
            return round(rate, 4)
        except Exception:
            return None

    # Completed reference years for growth calculation
    ref_year = today.year - 1 if today.year not in annual_totals or annual_totals[today.year] < (annual_dividend or 0) * 0.5 else today.year
    div_now = annual_totals.get(ref_year, annual_dividend or 0)

    growth_1y = cagr(annual_totals.get(ref_year - 1, 0), div_now, 1)
    growth_3y = cagr(annual_totals.get(ref_year - 3, 0), div_now, 3)
    growth_5y = cagr(annual_totals.get(ref_year - 5, 0), div_now, 5)
    growth_10y = cagr(annual_totals.get(ref_year - 10, 0), div_now, 10)

    # Coverage metrics
    payout_ratio: Optional[float] = None
    fcf_coverage: Optional[float] = None
    if financial:
        if financial.pe_ratio and financial.pe_ratio > 0 and trailing_yield:
            payout_ratio = round(trailing_yield * financial.pe_ratio, 4)
        if financial.free_cash_flow and financial.free_cash_flow > 0 and annual_dividend and financial.market_cap:
            est_total_payout = (annual_dividend / (latest_price or 1.0)) * financial.market_cap
            if est_total_payout > 0:
                fcf_coverage = round(financial.free_cash_flow / est_total_payout, 2)

    # ponytail: 4-pillar rule-based heuristic score (0-100); ceiling is simple thresholds, upgrade to multi-factor risk model if quantitative scoring needed
    score = 0.0
    # Pillar 1: History / Longevity (max 25)
    if years_paying >= 25:
        score += 25
    elif years_paying >= 10:
        score += 20
    elif years_paying >= 5:
        score += 15
    elif years_paying >= 2:
        score += 8

    # Pillar 2: Dividend Growth (max 25)
    effective_growth = growth_5y or growth_3y or growth_1y
    if effective_growth is not None:
        if effective_growth >= 0.08:
            score += 25
        elif effective_growth >= 0.05:
            score += 20
        elif effective_growth >= 0.02:
            score += 15
        elif effective_growth > 0:
            score += 10

    # Pillar 3: Yield Health (max 25)
    if current_yield is not None:
        if 0.02 <= current_yield <= 0.06:
            score += 25
        elif 0.015 <= current_yield <= 0.08:
            score += 18
        elif current_yield > 0:
            score += 10

    # Pillar 4: Financial Health / Payout Safety (max 25)
    has_financial_data = False
    if payout_ratio is not None:
        has_financial_data = True
        if 0.20 <= payout_ratio <= 0.60:
            score += 25
        elif 0.10 <= payout_ratio <= 0.75:
            score += 18
        elif payout_ratio <= 0.90:
            score += 12
    elif financial and financial.debt_to_equity is not None:
        has_financial_data = True
        if financial.debt_to_equity < 1.0:
            score += 20
        elif financial.debt_to_equity < 2.0:
            score += 12
        else:
            score += 5
    # Missing financial data earns 0 points (no free baseline)

    # ponytail: missing data penalty; ensure stocks with missing pillars or unverified coverage cannot earn 100/100
    has_all_data = (
        years_paying >= 2
        and effective_growth is not None
        and current_yield is not None
        and has_financial_data
        and (fcf_coverage is not None and fcf_coverage >= 1.0)
    )
    if not has_all_data:
        score = min(score, 85.0)

    quality_score = round(min(100.0, max(0.0, score)), 1)

    return ComputedDividendMetrics(
        current_yield=current_yield,
        trailing_yield=trailing_yield,
        forward_yield=forward_yield,
        annual_dividend=annual_dividend,
        payout_ratio=payout_ratio,
        fcf_coverage=fcf_coverage,
        growth_1y=growth_1y,
        growth_3y=growth_3y,
        growth_5y=growth_5y,
        growth_10y=growth_10y,
        years_paying=years_paying,
        years_growing=years_growing,
        quality_score=quality_score,
    )
