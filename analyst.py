"""
analyst.py  --  the ENGINE behind the single-stock research app.

Pure logic only: no UI in here. It does two jobs:
  1. get_snapshot(ticker)  -> gather price, stats, news, earnings into one dict
  2. compute_bias(snapshot) -> turn those facts into a transparent long/short lean

Keeping this separate from the Streamlit UI (app.py) means we can test it from
a plain terminal -- which is exactly how you build software you can trust.

HONEST FRAMING (read this, it matters):
  This is NOT a buy/sell signal and NOT alpha. Markets are roughly efficient.
  All this does is organize public evidence into a bull case and a bear case
  and show which way the weight of evidence leans -- with every reason stated.
  The signal weights below are a *judgment call*, not science. Don't tune them
  until the answer looks pretty -- that's overfitting, the cardinal sin.
"""

import yfinance as yf
import pandas as pd


# ---------------------------------------------------------------------------
# small formatting helpers (so the UI shows "35.2%" not "0.35199")
# ---------------------------------------------------------------------------
def pct(x):
    """Format a fraction as a percent, or '--' if missing."""
    return f"{x * 100:,.1f}%" if isinstance(x, (int, float)) else "--"


def num(x, dollars=False):
    """Format a number nicely, or '--' if missing."""
    if not isinstance(x, (int, float)):
        return "--"
    if dollars and abs(x) >= 1e9:
        return f"${x / 1e9:,.1f}B"
    if dollars and abs(x) >= 1e6:
        return f"${x / 1e6:,.1f}M"
    return f"{x:,.2f}"


# ---------------------------------------------------------------------------
# 1. GATHER THE DATA
# ---------------------------------------------------------------------------
def get_snapshot(ticker: str, light: bool = False) -> dict:
    """Pull everything we need about one stock into a single dict.

    light=True skips news + earnings + business summary. The screener uses
    this so it isn't pulling news for dozens of stocks it only wants to rank.
    """
    ticker = ticker.strip().upper()
    t = yf.Ticker(ticker)

    info = t.info                       # big fundamentals dict
    fast = t.fast_info                  # cheap price/MA/52wk numbers
    hist = t.history(period="1y")       # 1 year of daily prices (for chart + momentum)

    # 12-month price momentum = total return over the pulled window.
    mom_12m = None
    if not hist.empty:
        first, last = hist["Close"].iloc[0], hist["Close"].iloc[-1]
        mom_12m = (last / first) - 1

    snap = {
        "ticker": ticker,
        "name": info.get("shortName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),

        # price / trend
        "price": _safe(fast, "last_price"),
        "ma50": _safe(fast, "fifty_day_average"),
        "ma200": _safe(fast, "two_hundred_day_average"),
        "year_high": _safe(fast, "year_high"),
        "year_low": _safe(fast, "year_low"),
        "mom_12m": mom_12m,

        # value
        "pe": info.get("trailingPE"),
        "pb": info.get("priceToBook"),
        "ps": info.get("priceToSalesTrailing12Months"),

        # quality
        "roe": info.get("returnOnEquity"),
        "margin": info.get("profitMargins"),
        "de": info.get("debtToEquity"),

        # growth
        "rev_growth": info.get("revenueGrowth"),
        "earn_growth": info.get("earningsGrowth"),
        "market_cap": info.get("marketCap"),

        # valuation & analyst views (the heart of the under/over-valued verdict)
        "current_price": info.get("currentPrice"),
        "forward_pe": info.get("forwardPE"),
        "peg": info.get("trailingPegRatio") or info.get("pegRatio"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_rev": info.get("enterpriseToRevenue"),
        "fcf": info.get("freeCashflow"),
        "div_yield": info.get("dividendYield"),
        "gross_margin": info.get("grossMargins"),
        "target_mean": info.get("targetMeanPrice"),
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "rec_mean": info.get("recommendationMean"),     # 1=strong buy ... 5=sell
        "rec_key": info.get("recommendationKey"),
        "n_analysts": info.get("numberOfAnalystOpinions"),

        # extras
        "hist": hist,
        "summary": None if light else info.get("longBusinessSummary"),
        "news": [] if light else _clean_news(t),
        "next_earnings": None if light else _next_earnings(t),
        "earnings_history": [] if light else _earnings_history(t),
        "rec_trend": None if light else _rec_trend(t),
        "financials": {} if light else _financials(t),
    }
    return snap


def _financials(t, years=4):
    """Last few years of the income statement: revenue, net income, etc.
    yfinance returns these as a DataFrame (rows = line items, cols = year-ends).
    We pull the rows we care about, newest period first."""
    out = {}
    try:
        fin = t.income_stmt
        if fin is None or fin.empty:
            return out
        cols = list(fin.columns)[:years]

        def row(name):
            if name in fin.index:
                return [float(fin.loc[name, c]) if fin.loc[name, c] == fin.loc[name, c]
                        else None for c in cols]
            return [None] * len(cols)

        out = {
            "years": [str(c)[:4] for c in cols],
            "revenue": row("Total Revenue"),
            "net_income": row("Net Income"),
            "gross_profit": row("Gross Profit"),
            "operating_income": row("Operating Income"),
        }
    except Exception:
        pass
    return out


def _earnings_history(t, n=4):
    """Last n reported quarters: did they beat or miss EPS estimates?"""
    out = []
    try:
        ed = t.get_earnings_dates(limit=12)
        past = ed[ed["Reported EPS"].notna()].head(n)
        for date, row in past.iterrows():
            out.append({
                "date": date.strftime("%Y-%m-%d"),
                "estimate": row.get("EPS Estimate"),
                "reported": row.get("Reported EPS"),
                "surprise": row.get("Surprise(%)"),
            })
    except Exception:
        pass
    return out


def _rec_trend(t):
    """Current analyst buy/hold/sell counts + % bullish."""
    try:
        rec = t.recommendations
        row = rec[rec["period"] == "0m"].iloc[0]
        counts = {k: int(row[k]) for k in
                  ["strongBuy", "buy", "hold", "sell", "strongSell"]}
        total = sum(counts.values())
        bullish = counts["strongBuy"] + counts["buy"]
        return {"counts": counts, "total": total,
                "bullish_pct": bullish / total if total else None}
    except Exception:
        return None


def _safe(fast_info, key):
    """fast_info raises KeyError on missing keys; turn that into None."""
    try:
        return fast_info[key]
    except Exception:
        return None


def _clean_news(t, limit=6):
    """yfinance nests each story under ['content']; flatten to simple dicts."""
    out = []
    try:
        for item in (t.news or [])[:limit]:
            c = item.get("content", item)
            url = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url")
            out.append({
                "title": c.get("title"),
                "summary": c.get("summary"),
                "publisher": (c.get("provider") or {}).get("displayName"),
                "date": c.get("pubDate"),
                "url": url,
            })
    except Exception:
        pass
    return out


# Broad-market proxies we scrape headlines from for the general news feed.
# (ETFs + indices carry the market-wide / business stories, not single-name noise.)
MARKET_TICKERS = ["SPY", "QQQ", "DIA", "^GSPC", "^IXIC"]


def get_market_news(limit: int = 25) -> list:
    """Aggregate general business/market headlines across broad-market tickers.

    Pulls news for each proxy, de-duplicates by title (the same story shows up
    under several tickers), and sorts newest-first. ISO date strings sort
    correctly as plain text, so we can sort on them directly.
    """
    seen, out = set(), []
    for tk in MARKET_TICKERS:
        try:
            for n in _clean_news(yf.Ticker(tk), limit=15):
                title = n.get("title")
                if not title or title in seen:
                    continue
                seen.add(title)
                out.append(n)
        except Exception:
            continue
    out.sort(key=lambda n: n.get("date") or "", reverse=True)
    return out[:limit]


def _next_earnings(t):
    """Next earnings date if available (needs lxml). Optional -- never crash."""
    try:
        ed = t.get_earnings_dates(limit=4)
        future = ed[ed.index > pd.Timestamp.now(tz=ed.index.tz)]
        if not future.empty:
            return future.index.min().strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 2. TURN FACTS INTO A LONG/SHORT LEAN
# Each signal appends to bull[] or bear[] with a plain-English reason.
# A signal's `weight` says how much it counts. Net score -> overall lean.
# ---------------------------------------------------------------------------
def compute_bias(s: dict) -> dict:
    bull, bear = [], []          # lists of (reason, weight)
    p = s["price"]

    # --- TREND: price vs the 200-day moving average (the big-picture trend) ---
    if p and s["ma200"]:
        if p > s["ma200"]:
            bull.append((f"Price ${num(p)} is above its 200-day avg ${num(s['ma200'])} "
                         "-> primary trend is up.", 2))
        else:
            bear.append((f"Price ${num(p)} is below its 200-day avg ${num(s['ma200'])} "
                         "-> primary trend is down.", 2))

    # --- TREND: 50-day vs 200-day (golden cross / death cross) ---
    if s["ma50"] and s["ma200"]:
        if s["ma50"] > s["ma200"]:
            bull.append(("50-day avg is above the 200-day (golden-cross posture) "
                         "-> medium-term momentum supports the uptrend.", 1))
        else:
            bear.append(("50-day avg is below the 200-day (death-cross posture) "
                         "-> medium-term momentum is weak.", 1))

    # --- 12-MONTH MOMENTUM ---
    if s["mom_12m"] is not None:
        if s["mom_12m"] > 0.10:
            bull.append((f"Up {pct(s['mom_12m'])} over ~12 months "
                         "-> momentum factor is positive.", 2))
        elif s["mom_12m"] < -0.10:
            bear.append((f"Down {pct(s['mom_12m'])} over ~12 months "
                         "-> momentum factor is negative.", 2))

    # --- 52-WEEK RANGE POSITION ---
    if p and s["year_high"] and s["year_low"]:
        from_high = (p / s["year_high"]) - 1     # negative = below the high
        if from_high > -0.05:
            bull.append((f"Within {pct(abs(from_high))} of its 52-week high "
                         "-> strength, near the top of its range.", 1))
        elif p <= s["year_low"] * 1.05:
            bear.append(("Sitting near its 52-week low -> persistent weakness.", 1))

    # NOTE: valuation (P/E etc.) is intentionally NOT scored here -- it's owned
    # entirely by value_verdict() in valuation.py. Scoring it in both places
    # would double-count the same idea. This function stays trend + quality only.

    # --- QUALITY: return on equity ---
    if isinstance(s["roe"], (int, float)):
        if s["roe"] > 0.20:
            bull.append((f"ROE of {pct(s['roe'])} -> high-quality, efficient "
                         "use of capital.", 1))
        elif s["roe"] < 0.05:
            bear.append((f"ROE of {pct(s['roe'])} -> weak returns on capital.", 1))

    # --- GROWTH: earnings ---
    if isinstance(s["earn_growth"], (int, float)):
        if s["earn_growth"] > 0.10:
            bull.append((f"Earnings growing {pct(s['earn_growth'])} -> fundamentals "
                         "improving.", 1))
        elif s["earn_growth"] < 0:
            bear.append((f"Earnings shrinking ({pct(s['earn_growth'])}) "
                         "-> fundamentals deteriorating.", 1))

    # --- aggregate the votes ---
    bull_score = sum(w for _, w in bull)
    bear_score = sum(w for _, w in bear)
    net = bull_score - bear_score

    if net >= 3:
        lean = "LONG"
    elif net >= 1:
        lean = "LEAN LONG"
    elif net <= -3:
        lean = "SHORT"
    elif net <= -1:
        lean = "LEAN SHORT"
    else:
        lean = "NEUTRAL"

    return {
        "lean": lean,
        "net": net,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "bull": [r for r, _ in bull],
        "bear": [r for r, _ in bear],
    }


# ---------------------------------------------------------------------------
# quick self-test:  python analyst.py AAPL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    snap = get_snapshot(tk)
    bias = compute_bias(snap)
    print(f"\n{snap['name']} ({snap['ticker']}) -- {snap['sector']}")
    print(f"Price: ${num(snap['price'])}  | 12m: {pct(snap['mom_12m'])}  "
          f"| P/E: {num(snap['pe'])}  | ROE: {pct(snap['roe'])}")
    print(f"\n>>> LEAN: {bias['lean']}  (bull {bias['bull_score']} vs bear {bias['bear_score']})")
    print("\nBULL CASE:")
    for r in bias["bull"]:
        print("  +", r)
    print("\nBEAR CASE:")
    for r in bias["bear"]:
        print("  -", r)
    print(f"\nNews stories pulled: {len(snap['news'])}  | Next earnings: {snap['next_earnings']}")
