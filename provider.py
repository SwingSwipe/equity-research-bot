"""
provider.py  --  Finnhub data source (reliable on cloud, unlike Yahoo).

Yahoo Finance rate-limits shared cloud IPs; Finnhub is a real API with a key, so
it isn't IP-blocked. We use it on the cloud (and as a fallback) for the data its
free tier covers: live quote, fundamentals/ratios, analyst recommendation, news,
and earnings. Deep price history and price targets aren't on the free tier, so
those features degrade gracefully (the verdict leans on what's available).

The key is read from Streamlit secrets (st.secrets["FINNHUB_KEY"]) or the
FINNHUB_KEY env var, or the local .streamlit/secrets.toml — never hard-coded.
"""

import os

import requests

BASE = "https://finnhub.io/api/v1"


def get_key():
    """Find the Finnhub key from env, Streamlit secrets, or local secrets.toml."""
    k = os.environ.get("FINNHUB_KEY")
    if k:
        return k
    try:
        import streamlit as st
        if "FINNHUB_KEY" in st.secrets:
            return st.secrets["FINNHUB_KEY"]
    except Exception:
        pass
    try:
        import tomllib
        path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
        with open(path, "rb") as f:
            return tomllib.load(f).get("FINNHUB_KEY")
    except Exception:
        return None


def available() -> bool:
    return bool(get_key())


def _get(endpoint, **params):
    params["token"] = get_key()
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None                       # 403 (premium), 429 (rate limit), etc.


def _pct(x):
    """Finnhub returns many ratios as percentages (14.2 = 14.2%). Convert to a
    fraction (0.142) to match what the rest of the bot expects."""
    return (x / 100.0) if isinstance(x, (int, float)) else None


def get_snapshot_finnhub(ticker: str, light: bool = False) -> dict:
    """Assemble a snapshot dict (same keys as analyst.get_snapshot) from Finnhub."""
    ticker = ticker.strip().upper()
    quote = _get("quote", symbol=ticker) or {}
    profile = _get("stock/profile2", symbol=ticker) or {}
    metric = (_get("stock/metric", symbol=ticker, metric="all") or {}).get("metric", {})

    price = quote.get("c") or None                       # current price
    mcap = profile.get("marketCapitalization")           # in MILLIONS
    market_cap = mcap * 1e6 if isinstance(mcap, (int, float)) else None

    # debt/equity: Finnhub gives a ratio (~0.8); yfinance gives a percent (~80) --
    # match yfinance's scale so the rest of the bot's thresholds line up.
    de_raw = metric.get("totalDebt/totalEquityQuarterly")
    de = de_raw * 100 if isinstance(de_raw, (int, float)) else None
    # FCF from price/FCF-per-share: pfcf = marketcap/FCF  ->  FCF = marketcap/pfcf.
    pfcf = metric.get("pfcfShareTTM")
    fcf = (market_cap / pfcf) if (market_cap and isinstance(pfcf, (int, float)) and pfcf > 0) else None

    snap = {
        "ticker": ticker,
        "name": profile.get("name") or ticker,
        "sector": profile.get("finnhubIndustry"),        # Finnhub taxonomy (may not match GICS)
        "industry": profile.get("finnhubIndustry"),
        "price": price,
        "current_price": price,
        # value
        "pe": metric.get("peTTM"),
        "pb": metric.get("pb") or metric.get("pbQuarterly"),
        "ps": metric.get("psTTM"),
        "forward_pe": metric.get("forwardPE"),
        "peg": metric.get("pegTTM"),
        "ev_ebitda": metric.get("evEbitdaTTM"),
        "fcf": fcf,
        "div_yield": metric.get("currentDividendYieldTTM"),   # already a percent (0.38 = 0.38%)
        # quality
        "roe": _pct(metric.get("roeTTM")),
        "margin": _pct(metric.get("netProfitMarginTTM")),
        "gross_margin": _pct(metric.get("grossMarginTTM")),
        "de": de,
        # growth
        "rev_growth": _pct(metric.get("revenueGrowthTTMYoy")),
        "earn_growth": _pct(metric.get("epsGrowthTTMYoy")),
        "market_cap": market_cap,
        # analyst (price targets are premium -> None; recommendation is free, filled below)
        "target_mean": None, "target_high": None, "target_low": None,
        "rec_mean": None, "rec_key": None, "n_analysts": None,
        # history: no free candles, but 52wk range + 12-mo return ARE in metrics
        "ma50": None, "ma200": None,
        "year_high": metric.get("52WeekHigh"), "year_low": metric.get("52WeekLow"),
        "mom_12m": _pct(metric.get("52WeekPriceReturnDaily")), "hist": None,
        # extras
        "summary": None,
        "news": [] if light else _finnhub_news(ticker),
        "next_earnings": None, "earnings_history": [] if light else _finnhub_earnings(ticker),
        "rec_trend": None if light else _finnhub_rec(ticker),
        "financials": {},
    }

    # analyst recommendation -> rec_mean / rec_key / n_analysts
    rt = snap["rec_trend"]
    if rt and rt.get("total"):
        c = rt["counts"]
        # weighted 1=strong buy ... 5=sell
        score = (c["strongBuy"] * 1 + c["buy"] * 2 + c["hold"] * 3 +
                 c["sell"] * 4 + c["strongSell"] * 5)
        snap["rec_mean"] = round(score / rt["total"], 2)
        snap["n_analysts"] = rt["total"]
        snap["rec_key"] = ("buy" if snap["rec_mean"] <= 2.5 else
                           "hold" if snap["rec_mean"] < 3.5 else "sell")
    return snap


def _finnhub_news(ticker, limit=6):
    import datetime as _dt
    try:
        today = _dt.date.today()
        frm = (today - _dt.timedelta(days=14)).isoformat()
        data = _get("company-news", symbol=ticker, **{"from": frm, "to": today.isoformat()}) or []
        out = []
        for n in data[:limit]:
            out.append({
                "title": n.get("headline"), "summary": n.get("summary"),
                "publisher": n.get("source"), "url": n.get("url"),
                "date": _dt.datetime.utcfromtimestamp(n.get("datetime", 0)).isoformat() + "Z"
                        if n.get("datetime") else None,
            })
        return out
    except Exception:
        return []


def _finnhub_earnings(ticker, n=4):
    try:
        data = _get("stock/earnings", symbol=ticker) or []
        out = []
        for e in data[:n]:
            out.append({
                "date": f"{e.get('year')}Q{e.get('quarter')}",
                "estimate": e.get("estimate"), "reported": e.get("actual"),
                "surprise": e.get("surprisePercent"),
            })
        return out
    except Exception:
        return []


def _finnhub_rec(ticker):
    try:
        data = _get("stock/recommendation", symbol=ticker) or []
        if not data:
            return None
        r = data[0]                    # most recent period
        counts = {"strongBuy": r.get("strongBuy", 0), "buy": r.get("buy", 0),
                  "hold": r.get("hold", 0), "sell": r.get("sell", 0),
                  "strongSell": r.get("strongSell", 0)}
        total = sum(counts.values())
        bullish = counts["strongBuy"] + counts["buy"]
        return {"counts": counts, "total": total,
                "bullish_pct": bullish / total if total else None}
    except Exception:
        return None


if __name__ == "__main__":
    import sys, json
    if not available():
        print("No FINNHUB_KEY found (set env var or .streamlit/secrets.toml).")
        raise SystemExit
    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    s = get_snapshot_finnhub(tk)
    print(f"{s['name']} ({tk}) | price {s['price']} | P/E {s['pe']} | ROE {s['roe']} | "
          f"rating {s['rec_mean']} ({s['n_analysts']} analysts) | target {s['target_mean']}")
    print("news:", len(s["news"]), "| earnings:", len(s["earnings_history"]))
