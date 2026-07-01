"""
catalysts.py  --  "what's worth looking at right now?"

This is the idea-discovery engine. Instead of you already knowing a ticker, it
surfaces stocks with a CATALYST -- a reason they're in play today:

  * Today's big movers        (gainers / losers / most active)
  * Upcoming earnings          (about to report -> news risk + opportunity)
  * Recent earnings surprises  (just reported -> beat or missed)
  * IPOs                       (brand-new listings)

All free via yfinance's predefined screeners and calendar endpoints.

HONEST NOTE: a catalyst is a REASON TO LOOK, not a reason to buy. A stock up 20%
today may be a great story or a pump that's already over. The point is to give
you a shortlist to actually research (in the Stock Research tab), not signals.
"""

import pandas as pd
import yfinance as yf


def _use_finnhub():
    """True on the cloud (where Yahoo is throttled and Finnhub is used)."""
    try:
        import analyst
        return analyst.USE_FINNHUB
    except Exception:
        return False


# ---------------------------------------------------------------------------
# TODAY'S MOVERS  (Yahoo's predefined screeners)
# ---------------------------------------------------------------------------
def get_movers(which: str = "day_gainers", limit: int = 15) -> pd.DataFrame:
    """which: 'day_gainers' | 'day_losers' | 'most_actives'. Returns a tidy table."""
    result = yf.screen(which)
    quotes = result.get("quotes", []) if isinstance(result, dict) else []
    rows = [{
        "Symbol": q.get("symbol"),
        "Name": q.get("shortName"),
        "Price": q.get("regularMarketPrice"),
        "% Change": q.get("regularMarketChangePercent"),
        "Mkt Cap": q.get("marketCap"),
    } for q in quotes[:limit]]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# EARNINGS  (the calendar carries both upcoming and just-reported)
# ---------------------------------------------------------------------------
def get_upcoming_earnings(days: int = 7, limit: int = 25) -> pd.DataFrame:
    """Companies reporting in the next `days` days, soonest first.
    Timing codes: BMO = before market open, AMC = after market close."""
    if _use_finnhub():
        from provider import get_earnings_finnhub
        return get_earnings_finnhub(days, limit)
    now = pd.Timestamp.now(tz="UTC")
    cals = yf.Calendars(start=now, end=now + pd.Timedelta(days=days))
    df = cals.get_earnings_calendar()
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[df["Event Start Date"] >= now].sort_values("Event Start Date")
    cols = ["Company", "Event Start Date", "Timing", "EPS Estimate", "Marketcap"]
    return d[cols].head(limit).reset_index()        # keep Symbol as a column


def get_recent_surprises(days: int = 3, limit: int = 20) -> pd.DataFrame:
    """Companies that JUST reported -- did they beat or miss? Sorted by surprise."""
    now = pd.Timestamp.now(tz="UTC")
    cals = yf.Calendars(start=now - pd.Timedelta(days=days), end=now)
    df = cals.get_earnings_calendar()
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[df["Reported EPS"].notna()].copy()
    d = d.sort_values("Surprise(%)", ascending=False)
    cols = ["Company", "Event Start Date", "EPS Estimate", "Reported EPS", "Surprise(%)"]
    return d[cols].head(limit).reset_index()


# ---------------------------------------------------------------------------
# IPOs  (brand-new listings)
# ---------------------------------------------------------------------------
def get_ipos(days_back: int = 5, days_fwd: int = 14, limit: int = 25,
             exclude_funds: bool = True) -> pd.DataFrame:
    """Recent + upcoming IPOs in a window around today.

    Yahoo's IPO feed is noisy -- it's dominated by ETF/fund launches, not real
    operating-company IPOs. exclude_funds drops the obvious ones by name so the
    list shows actual companies going public.
    """
    if _use_finnhub():
        from provider import get_ipos_finnhub
        return get_ipos_finnhub(days_fwd, limit)
    now = pd.Timestamp.now(tz="UTC")
    cals = yf.Calendars(start=now - pd.Timedelta(days=days_back),
                        end=now + pd.Timedelta(days=days_fwd))
    df = cals.get_ipo_info_calendar()
    if df is None or df.empty:
        return pd.DataFrame()
    if exclude_funds:
        fund_words = r"ETF|Fund|Trust|CLO|Index|Portfolio|ETN"
        df = df[~df["Company"].str.contains(fund_words, case=False, na=False)]
    cols = ["Company", "Exchange", "Date", "Price From", "Price To", "Action"]
    keep = [c for c in cols if c in df.columns]
    return df[keep].sort_values("Date").head(limit).reset_index()


if __name__ == "__main__":
    print("=== TOP GAINERS ===")
    print(get_movers("day_gainers", 5).to_string(index=False))
    print("\n=== UPCOMING EARNINGS (7d) ===")
    print(get_upcoming_earnings(7, 6).to_string(index=False))
    print("\n=== RECENT SURPRISES ===")
    print(get_recent_surprises(3, 6).to_string(index=False))
    print("\n=== IPOs ===")
    print(get_ipos(limit=6).to_string(index=False))
