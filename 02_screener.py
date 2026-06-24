"""
02_screener.py  --  rank a universe with a multi-factor composite score.

THE BIG IDEA: factors are measured in different units (P/E is ~15-40, ROE is
0.05-1.4, momentum is a percentage). You can't average them directly. So we
convert each metric to a Z-SCORE -- "how many standard deviations from the
universe average is this stock?" -- which puts everything on one neutral scale.
Then we average the z-scores into factor groups, and average the groups into a
single composite. Highest composite = best-ranked.

TWO UPGRADES over the first version:
  1. UNIVERSE = the real, live S&P 500 (scraped) instead of a hand-typed list.
  2. WINSORIZE = before z-scoring, clip each metric to its 2nd/98th percentile.
     One freak value (NVDA's enormous earnings growth) otherwise stretches the
     whole distribution and drowns out every other stock. Funds do this routinely.

Four factor groups (equal-weighted -- equal on purpose: tuning weights until the
ranking 'looks right' is overfitting):
  VALUE     -> cheap on earnings / book / sales        (higher yield = better)
  QUALITY   -> high ROE, fat margins, low debt         (higher = better)
  GROWTH    -> revenue & earnings growing              (higher = better)
  MOMENTUM  -> 12-mo return, price above its 200-day    (higher = better)

Run:  python 02_screener.py
Output: a ranked table + ranked_watchlist.csv
"""

import time
import numpy as np
import pandas as pd

from analyst import get_snapshot
from universe import get_sp500

# How many names to screen. Pulling fundamentals on free data is SLOW (~1.5s per
# stock), so the full 503 takes several minutes and can hit rate limits. Start
# with a sample; set LIMIT = None to run the entire S&P 500 when you have time.
LIMIT = 40


def build_universe(limit):
    sp = get_sp500()
    if limit:
        sp = sp.head(limit)
    return sp.set_index("Ticker")          # index = Ticker, columns include Sector


def gather(tickers) -> pd.DataFrame:
    """Pull a light snapshot per ticker and assemble one raw-metrics table."""
    rows = []
    for i, tk in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {tk} ...")
        try:
            s = get_snapshot(tk, light=True)     # light=True: skip news/earnings
            rows.append({
                "Ticker": tk,
                "pe": s["pe"], "pb": s["pb"], "ps": s["ps"],
                "roe": s["roe"], "margin": s["margin"], "de": s["de"],
                "rev_growth": s["rev_growth"], "earn_growth": s["earn_growth"],
                "mom_12m": s["mom_12m"],
                "trend": (s["price"] / s["ma200"] - 1)
                         if s["price"] and s["ma200"] else np.nan,
            })
        except Exception as e:
            print(f"    !! {tk} failed: {e}")
        time.sleep(0.25)
    return pd.DataFrame(rows).set_index("Ticker")


def winsorize(s: pd.Series, lower=0.02, upper=0.98) -> pd.Series:
    """Clip a series to its 2nd/98th percentile so outliers don't dominate."""
    lo, hi = s.quantile(lower), s.quantile(upper)
    return s.clip(lo, hi)


def z(series: pd.Series) -> pd.Series:
    """Winsorize, then z-score: (value - mean) / std. NaNs stay NaN."""
    s = winsorize(series)
    std = s.std()
    if not std or np.isnan(std):
        return s * 0.0                       # no spread -> everyone neutral
    return (s - s.mean()) / std


def score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # --- VALUE: use YIELDS (1/ratio) so "cheaper = higher = better".
    # A negative/zero ratio (e.g. negative book) isn't "cheap", it's broken ->
    # treat as missing so it scores neutral, not great.
    earnings_yield = 1 / out["pe"].where(out["pe"] > 0)
    book_yield     = 1 / out["pb"].where(out["pb"] > 0)
    sales_yield    = 1 / out["ps"].where(out["ps"] > 0)
    out["VALUE"] = pd.concat(
        [z(earnings_yield), z(book_yield), z(sales_yield)], axis=1
    ).mean(axis=1)

    # --- QUALITY: high ROE, high margin, LOW debt (negate debt's z).
    out["QUALITY"] = pd.concat(
        [z(out["roe"]), z(out["margin"]), -z(out["de"])], axis=1
    ).mean(axis=1)

    # --- GROWTH: revenue + earnings growth.
    out["GROWTH"] = pd.concat(
        [z(out["rev_growth"]), z(out["earn_growth"])], axis=1
    ).mean(axis=1)

    # --- MOMENTUM: 12-month return + distance above the 200-day trend.
    out["MOMENTUM"] = pd.concat(
        [z(out["mom_12m"]), z(out["trend"])], axis=1
    ).mean(axis=1)

    # --- COMPOSITE: equal-weight the four groups (NaN group -> 0 neutral).
    groups = ["VALUE", "QUALITY", "GROWTH", "MOMENTUM"]
    out["COMPOSITE"] = out[groups].fillna(0).mean(axis=1)
    out["RANK"] = out["COMPOSITE"].rank(ascending=False).astype(int)
    return out.sort_values("COMPOSITE", ascending=False)


def main():
    print(f"Building universe (S&P 500, limit={LIMIT}) ...")
    uni = build_universe(LIMIT)

    print(f"Gathering data for {len(uni)} stocks (this takes a bit) ...")
    raw = gather(uni.index.tolist())

    print("\nScoring & ranking ...")
    ranked = score(raw)
    ranked["Sector"] = uni["Sector"]            # attach sector for readability

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)

    show = ["Sector", "VALUE", "QUALITY", "GROWTH", "MOMENTUM", "COMPOSITE", "RANK"]
    print("\n=== TOP 15 RANKED (best composite at top) ===")
    print(ranked[show].head(15))

    ranked.to_csv("ranked_watchlist.csv")
    print(f"\nSaved all {len(ranked)} ranked names -> ranked_watchlist.csv")

    print("\nNOTE: equal factor weights, no trading costs, and this is TODAY's")
    print("S&P 500 (survivorship-filtered -- delisted names are absent). It ranks")
    print("what looks good NOW; it does NOT prove these names beat the market.")


if __name__ == "__main__":
    main()
