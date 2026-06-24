"""
02_screener.py  --  rank the whole universe with a multi-factor composite score.

THE BIG IDEA: factors are measured in different units (P/E is ~15-40, ROE is
0.05-1.4, momentum is a percentage). You can't average them directly. So we
convert each metric to a Z-SCORE -- "how many standard deviations from the
universe average is this stock?" -- which puts everything on one neutral scale.
Then we average the z-scores into factor groups, and average the groups into a
single composite. Highest composite = best-ranked.

Four factor groups (equal-weighted -- and that EQUAL weighting is on purpose:
the moment you tune weights to make the ranking 'look right', you're overfitting):
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

# Reuse the same universe idea. (Later: swap this for the full S&P 500.)
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "HD", "MCD", "KO", "JPM",
    "BAC", "V", "JNJ", "UNH", "PFE", "XOM", "CVX", "CAT",
]


def gather(universe) -> pd.DataFrame:
    """Pull a light snapshot per ticker and assemble one raw-metrics table."""
    rows = []
    for tk in universe:
        print(f"  {tk} ...")
        try:
            s = get_snapshot(tk, light=True)     # light=True: skip news/earnings
            rows.append({
                "Ticker": tk, "Sector": s["sector"],
                "pe": s["pe"], "pb": s["pb"], "ps": s["ps"],
                "roe": s["roe"], "margin": s["margin"], "de": s["de"],
                "rev_growth": s["rev_growth"], "earn_growth": s["earn_growth"],
                "mom_12m": s["mom_12m"],
                # how far price sits above/below its 200-day average:
                "trend": (s["price"] / s["ma200"] - 1)
                         if s["price"] and s["ma200"] else np.nan,
            })
        except Exception as e:
            print(f"    !! {tk} failed: {e}")
        time.sleep(0.3)
    return pd.DataFrame(rows).set_index("Ticker")


def z(series: pd.Series) -> pd.Series:
    """Z-score: (value - mean) / std. NaNs stay NaN (mean/std skip them)."""
    std = series.std()
    if not std or np.isnan(std):
        return series * 0.0                      # no spread -> everyone neutral
    return (series - series.mean()) / std


def score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # --- VALUE: use YIELDS (1/ratio) so "cheaper = higher = better".
    # Guard: a negative or zero ratio (e.g. AAPL/MCD negative book) isn't
    # "cheap", it's broken -- treat as missing so it scores neutral, not great.
    earnings_yield = 1 / out["pe"].where(out["pe"] > 0)
    book_yield     = 1 / out["pb"].where(out["pb"] > 0)
    sales_yield    = 1 / out["ps"].where(out["ps"] > 0)
    out["VALUE"] = pd.concat(
        [z(earnings_yield), z(book_yield), z(sales_yield)], axis=1
    ).mean(axis=1)

    # --- QUALITY: high ROE, high margin, LOW debt (so negate debt's z).
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

    # --- COMPOSITE: equal-weight the four groups.
    # A group can be NaN if every input was missing -> treat as 0 (neutral).
    groups = ["VALUE", "QUALITY", "GROWTH", "MOMENTUM"]
    out["COMPOSITE"] = out[groups].fillna(0).mean(axis=1)

    out["RANK"] = out["COMPOSITE"].rank(ascending=False).astype(int)
    return out.sort_values("COMPOSITE", ascending=False)


def main():
    print("Gathering data for the universe ...")
    raw = gather(UNIVERSE)

    print("\nScoring & ranking ...")
    ranked = score(raw)

    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)

    show = ["Sector", "VALUE", "QUALITY", "GROWTH", "MOMENTUM", "COMPOSITE", "RANK"]
    print("\n=== RANKED WATCHLIST (best composite at top) ===")
    print(ranked[show])

    ranked.to_csv("ranked_watchlist.csv")
    print("\nSaved -> ranked_watchlist.csv")

    print("\nNOTE: equal factor weights, no costs, and this is TODAY's universe")
    print("(survivorship-filtered). It's a ranking of what looks good now --")
    print("NOT proof these names beat the market. That's the backtest's job, later.")


if __name__ == "__main__":
    main()
