"""
smallcap.py  --  Small-Cap Explorer: triage smaller stocks for RED FLAGS.

READ THIS, IT'S THE WHOLE POINT.
There is no tool that finds penny stocks that will "boom" -- if there were, its
owner would keep it. This corner of the market is where most money goes to die:
pump-and-dumps, dying companies, and survivorship bias (you hear about the one
that mooned, never the 99 that went to zero). Research backs this up: quality
small-caps compound over time while speculative "junk" small-caps have NEGATIVE
long-run returns -- the recent junk rallies are a "mirage" of retail speculation
(WisdomTree, Jan 2026; "Quality Minus Junk", Asness/Frazzini/Pedersen).

So this tool does NOT predict booms. Its job is the opposite and far more useful:
flag the traps. It pulls Yahoo's small-cap movers and marks the red flags that
the SEC/FINRA warn about, so you can tell "small company with a real business"
from "lottery ticket / likely pump." It ranks by RISK (low first), never by
upside. Even the least-flagged names here are high-risk. Not investment advice.

Red-flag criteria are grounded in SEC/FINRA microcap-fraud guidance + standard
quality screening (profitability, liquidity, leverage).
"""

import pandas as pd
import yfinance as yf

# Yahoo predefined screens that return small/speculative names. These lean toward
# today's MOVERS -- which is exactly where pumps show up, so it's the right pond
# to fish in for a *fraud filter* (we surface them, then flag the junk).
SMALLCAP_QUERIES = ["small_cap_gainers", "aggressive_small_caps", "small_cap_gainers"]


def _candidates(max_price=10.0, max_cap=2e9, per_query=40):
    """Pull + dedupe small-cap quotes from the predefined screens."""
    seen, rows = set(), []
    for q in dict.fromkeys(SMALLCAP_QUERIES):
        try:
            res = yf.screen(q)
            for c in (res.get("quotes", []) if isinstance(res, dict) else [])[:per_query]:
                sym = c.get("symbol")
                price = c.get("regularMarketPrice")
                cap = c.get("marketCap")
                if not sym or sym in seen or price is None:
                    continue
                if price > max_price or (cap and cap > max_cap):
                    continue
                seen.add(sym)
                rows.append(c)
        except Exception:
            continue
    return rows


def _flags(c) -> tuple:
    """Return (risk_score, [red-flag strings], profitable_bool) for one quote."""
    flags = []
    risk = 0
    sym = c.get("symbol", "")
    price = c.get("regularMarketPrice") or 0
    cap = c.get("marketCap") or 0
    chg = c.get("regularMarketChangePercent") or 0
    vol = c.get("regularMarketVolume") or 0
    avg = c.get("averageDailyVolume3Month") or 0
    eps = c.get("epsTrailingTwelveMonths")
    low = c.get("fiftyTwoWeekLow")

    if price < 1:
        flags.append("Sub-$1 penny price — extreme volatility, dilution & delisting risk."); risk += 2
    elif price < 5:
        flags.append("Penny-stock territory (<$5)."); risk += 1

    if cap and cap < 50e6:
        flags.append("Nano-cap (<$50M) — tiny float, easily manipulated."); risk += 2
    elif cap and cap < 300e6:
        flags.append("Micro-cap (<$300M) — thin analyst coverage & liquidity."); risk += 1

    profitable = isinstance(eps, (int, float)) and eps > 0
    if not profitable:
        flags.append("Unprofitable (no positive trailing EPS) — burning cash, often "
                     "funded by issuing/diluting shares."); risk += 2

    vol_ratio = (vol / avg) if avg else None
    if vol_ratio and vol_ratio > 3 and chg > 20:
        flags.append(f"Spiking {chg:+.0f}% on ~{vol_ratio:.0f}x normal volume — the "
                     "classic pump pattern the SEC warns about."); risk += 3
    elif vol_ratio and vol_ratio > 3:
        flags.append(f"Volume ~{vol_ratio:.0f}x its average — unusual, unexplained activity."); risk += 1

    dollar_vol = price * avg
    if dollar_vol and dollar_vol < 1e6:
        flags.append("Very low dollar volume — illiquid; you may not be able to sell."); risk += 2

    if sym.endswith("Q"):
        flags.append("Ticker ends in 'Q' — company is in bankruptcy."); risk += 3

    if low and price <= low * 1.10:
        flags.append("Near its 52-week low — persistent decline; the market may know something."); risk += 1

    return risk, flags, profitable


def _risk_level(risk):
    if risk >= 6:
        return "🔴 Extreme / likely trap"
    if risk >= 3:
        return "🟠 Very high"
    return "🟡 High (it's still a small-cap)"


def explore_smallcaps(max_price=10.0, max_cap=2e9) -> pd.DataFrame:
    """Return a triaged table of small-cap movers, lowest-risk first."""
    rows = []
    for c in _candidates(max_price, max_cap):
        risk, flags, profitable = _flags(c)
        cap = c.get("marketCap") or 0
        rows.append({
            "Symbol": c.get("symbol"),
            "Name": (c.get("shortName") or "")[:28],
            "Price": round(c.get("regularMarketPrice") or 0, 3),
            "Cap ($M)": round(cap / 1e6, 0) if cap else None,
            "Today %": round(c.get("regularMarketChangePercent") or 0, 1),
            "Profitable": "✓" if profitable else "✗",
            "Risk": _risk_level(risk),
            "_risk": risk,
            "Flags": len(flags),
            "Top concern": flags[0] if flags else "—",
            "_all_flags": flags,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # lowest risk + profitable first (the closest thing to 'has a real business')
    return df.sort_values(["_risk", "Profitable"], ascending=[True, False]).reset_index(drop=True)


if __name__ == "__main__":
    df = explore_smallcaps()
    cols = ["Symbol", "Price", "Cap ($M)", "Today %", "Profitable", "Risk", "Flags"]
    print(f"{len(df)} small-cap candidates (lowest risk first):\n")
    print(df[cols].head(20).to_string(index=False))
    print(f"\nProfitable: {(df['Profitable']=='✓').sum()} / {len(df)}")
