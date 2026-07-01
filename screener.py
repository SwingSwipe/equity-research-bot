"""
screener.py  --  multi-factor S&P 500 ranking engine (reusable).

Ranks a universe on a composite of VALUE / QUALITY / GROWTH / MOMENTUM using
cross-sectional, winsorized z-scores (see 02_screener.py for the teaching version).
The app displays a pre-computed snapshot (screen_ranked.csv) so the live site is
instant and doesn't hammer the data API; rows are still clickable into live research.

Regenerate the snapshot:  python screener.py
"""

import time

import numpy as np
import pandas as pd

from analyst import get_snapshot


def _winsorize(s, lo=0.02, hi=0.98):
    return s.clip(s.quantile(lo), s.quantile(hi))


def _z(s):
    s = _winsorize(s)
    sd = s.std()
    return (s - s.mean()) / sd if sd and not np.isnan(sd) else s * 0.0


def screen_universe(tickers) -> pd.DataFrame:
    """Pull light snapshots, score 4 factor groups, rank by composite."""
    rows = []
    for i, tk in enumerate(tickers, 1):
        try:
            s = get_snapshot(tk, light=True)
            if not (s.get("price") or s.get("current_price")):
                continue
            rows.append({
                "Ticker": tk, "Sector": s.get("sector"),
                "Price": round(s.get("price") or s.get("current_price") or 0, 2),
                "pe": s["pe"], "pb": s["pb"], "ps": s["ps"], "roe": s["roe"],
                "margin": s["margin"], "de": s["de"], "rev_growth": s["rev_growth"],
                "earn_growth": s["earn_growth"], "mom_12m": s["mom_12m"],
                "trend": (s["price"] / s["ma200"] - 1) if (s.get("price") and s.get("ma200")) else np.nan,
            })
        except Exception:
            pass
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.set_index("Ticker")

    ey = 1 / df["pe"].where(df["pe"] > 0)
    by = 1 / df["pb"].where(df["pb"] > 0)
    sy = 1 / df["ps"].where(df["ps"] > 0)
    df["VALUE"] = pd.concat([_z(ey), _z(by), _z(sy)], axis=1).mean(axis=1)
    df["QUALITY"] = pd.concat([_z(df["roe"]), _z(df["margin"]), -_z(df["de"])], axis=1).mean(axis=1)
    df["GROWTH"] = pd.concat([_z(df["rev_growth"]), _z(df["earn_growth"])], axis=1).mean(axis=1)
    df["MOMENTUM"] = pd.concat([_z(df["mom_12m"]), _z(df["trend"])], axis=1).mean(axis=1)

    groups = ["VALUE", "QUALITY", "GROWTH", "MOMENTUM"]
    df["COMPOSITE"] = df[groups].fillna(0).mean(axis=1)
    df["RANK"] = df["COMPOSITE"].rank(ascending=False).astype(int)
    keep = ["Sector", "Price"] + groups + ["COMPOSITE", "RANK"]
    return df[keep].sort_values("COMPOSITE", ascending=False).round(2).reset_index()


if __name__ == "__main__":
    from datetime import datetime
    from universe import get_sp500

    LIMIT = 150     # snapshot universe (None = full 503, slower)
    sp = get_sp500()
    tickers = sp["Ticker"].tolist()[:LIMIT] if LIMIT else sp["Ticker"].tolist()
    print(f"Screening {len(tickers)} stocks…")
    ranked = screen_universe(tickers)
    ranked.attrs["as_of"] = datetime.today().strftime("%Y-%m-%d")
    ranked.to_csv("screen_ranked.csv", index=False)
    print(f"\nTop 15 (of {len(ranked)}):")
    print(ranked.head(15).to_string(index=False))
    print(f"\nSaved -> screen_ranked.csv ({datetime.today():%Y-%m-%d})")
