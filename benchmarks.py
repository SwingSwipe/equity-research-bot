"""
benchmarks.py  --  sector-median valuation multiples.

WHY: "P/E of 25" means nothing in isolation. It's cheap for software and
expensive for a utility. To judge a stock's valuation honestly we compare its
multiples to ITS SECTOR's typical levels. This module computes those sector
medians from a sample of the S&P 500 and saves them to sector_benchmarks.json.

The medians are keyed by yfinance's own sector names (e.g. "Technology",
"Financial Services") so they line up with what get_snapshot() returns per stock.

HONEST LIMITS:
  * Medians from a small sample are rough; more names = better. Re-run with a
    bigger LIMIT (or LIMIT=None for the full index) when you have time.
  * Sector medians drift slowly, so re-running monthly is plenty.
  * A few sectors (e.g. Real Estate) have few S&P names; treat thin sectors gently.
"""

import json
import os
import statistics
import time

import yfinance as yf

BENCH_FILE = os.path.join(os.path.dirname(__file__), "sector_benchmarks.json")
METRICS = ["pe", "pb", "ps", "ev_ebitda", "fcf_yield"]

_CACHE = None


def load_benchmarks() -> dict:
    """Read sector benchmarks (memoized). Returns {} if not built yet."""
    global _CACHE
    if _CACHE is None:
        try:
            with open(BENCH_FILE, "r") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    return _CACHE


def _fetch_multiples(tk: str) -> dict:
    """Just the .info multiples we need -- no price history, so it's fast."""
    info = yf.Ticker(tk).info
    mc, fcf = info.get("marketCap"), info.get("freeCashflow")
    return {
        "sector": info.get("sector"),
        "pe": info.get("trailingPE"),
        "pb": info.get("priceToBook"),
        "ps": info.get("priceToSalesTrailing12Months"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "fcf_yield": (fcf / mc) if (fcf and mc) else None,
    }


def build_benchmarks(tickers) -> dict:
    """Pull multiples for each ticker, group by sector, take medians."""
    buckets = {}                       # sector -> {metric: [values]}
    for i, tk in enumerate(tickers, 1):
        try:
            m = _fetch_multiples(tk)
            sec = m["sector"]
            if not sec:
                continue
            b = buckets.setdefault(sec, {k: [] for k in METRICS})
            for k in METRICS:
                v = m[k]
                # only keep sane, positive multiples (a negative P/E isn't "cheap")
                if isinstance(v, (int, float)) and v > 0 and v == v:
                    b[k].append(v)
        except Exception as e:
            print(f"  !! {tk}: {e}")
        if i % 20 == 0:
            print(f"  …{i}/{len(tickers)}")
        time.sleep(0.2)

    out = {}
    for sec, b in buckets.items():
        out[sec] = {"_n": max(len(b[k]) for k in METRICS)}
        for k in METRICS:
            if b[k]:
                out[sec][k] = round(statistics.median(b[k]), 3)
    return out


def save_benchmarks(bench: dict):
    with open(BENCH_FILE, "w") as f:
        json.dump(bench, f, indent=2)


if __name__ == "__main__":
    from datetime import datetime
    from universe import get_sp500

    LIMIT = 90        # sample size; set None for the full S&P 500 (slow)
    sp = get_sp500()
    tickers = sp["Ticker"].tolist()
    if LIMIT:
        tickers = tickers[:LIMIT]

    print(f"Building sector benchmarks from {len(tickers)} stocks…")
    bench = build_benchmarks(tickers)
    bench["_meta"] = {"built": datetime.today().strftime("%Y-%m-%d"),
                      "sample": len(tickers)}
    save_benchmarks(bench)

    print("\nSector medians:")
    for sec, b in bench.items():
        if sec == "_meta":
            continue
        pe = b.get("pe", "--")
        ev = b.get("ev_ebitda", "--")
        print(f"  {sec:24} (n={b.get('_n','?'):>2})  P/E {pe}  EV/EBITDA {ev}")
