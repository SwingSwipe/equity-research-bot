"""
tracker.py  --  the bot's report card.

This is the most important reliability tool we have, because it's the only one
that tells us whether the verdicts are actually RIGHT. It works in two steps:

  1. log_verdicts()  -- record today's verdicts (date, ticker, price, stance...)
     to a CSV. This is a FORWARD record: we only ever compare it to the future,
     so there's no lookahead cheating.
  2. score_log()     -- for each past verdict, pull the current price, compute
     the return since, and -- crucially -- subtract the S&P 500's return over the
     same window. Beating the market is the only bar that counts. Then group by
     stance: did BUY leans actually beat AVOIDs?

HONEST LIMITS:
  * This only becomes meaningful after weeks/months pass. Fresh returns are noise.
  * A handful of names over a few weeks proves nothing -- you need many verdicts
    over long windows before the numbers mean anything. Small samples lie.
  * It validates the verdicts going forward; it does NOT backtest history (we
    can't, cleanly -- yfinance gives today's fundamentals, not point-in-time).
"""

import os
from datetime import datetime

import pandas as pd
import yfinance as yf

LOG_FILE = os.path.join(os.path.dirname(__file__), "verdicts_log.csv")
LOG_COLS = ["date", "ticker", "price", "stance", "valuation", "upside", "trend", "confidence"]


def load_log() -> pd.DataFrame:
    try:
        df = pd.read_csv(LOG_FILE)
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=LOG_COLS)


def log_verdicts(board_rows) -> int:
    """Append today's verdicts. Dedupe so re-logging the same day is harmless."""
    today = datetime.today().strftime("%Y-%m-%d")
    new = pd.DataFrame([{
        "date": today,
        "ticker": r["Ticker"],
        "price": r["Price"],
        "stance": r["Stance"],
        "valuation": r["Valuation"],
        "upside": r.get("Upside %"),
        "trend": r["Trend"],
        "confidence": r["Confidence"],
    } for r in board_rows])
    combined = pd.concat([load_log(), new], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "ticker"], keep="last")
    combined.to_csv(LOG_FILE, index=False)
    return len(new)


def score_log() -> dict | None:
    """Grade every logged verdict by its return-since vs the S&P 500."""
    log = load_log()
    if log.empty:
        return None
    log = log.copy()
    log["date"] = pd.to_datetime(log["date"])
    tickers = sorted(log["ticker"].unique().tolist())
    start = log["date"].min().strftime("%Y-%m-%d")

    try:
        data = yf.download(tickers + ["SPY"], start=start, progress=False)["Close"]
    except Exception:
        return None
    if isinstance(data, pd.Series):
        data = data.to_frame()
    data = data.sort_index()
    if "SPY" not in data.columns or data.empty:
        return None

    spy = data["SPY"].dropna()
    spy_now = spy.iloc[-1]
    last_day = data.index[-1]

    rows = []
    for _, r in log.iterrows():
        tk = r["ticker"]
        if tk not in data.columns:
            continue
        series = data[tk].dropna()
        if series.empty or not r["price"]:
            continue
        cur = series.iloc[-1]
        stock_ret = cur / r["price"] - 1
        spy_at = spy.asof(r["date"])              # SPY level on the log date
        spy_ret = (spy_now / spy_at - 1) if spy_at == spy_at else None
        excess = (stock_ret - spy_ret) if spy_ret is not None else None
        rows.append({
            "date": r["date"].strftime("%Y-%m-%d"),
            "ticker": tk, "stance": r["stance"], "valuation": r["valuation"],
            "trend": r["trend"], "confidence": r["confidence"],
            "logged_price": round(r["price"], 2), "current_price": round(cur, 2),
            "return_%": round(stock_ret * 100, 1),
            "vs_SPY_%": round(excess * 100, 1) if excess is not None else None,
            "days": (last_day - r["date"]).days,
        })

    detail = pd.DataFrame(rows)
    if detail.empty:
        return None

    graded = detail.dropna(subset=["vs_SPY_%"])
    summary = (graded.groupby("stance")
               .agg(n=("ticker", "size"),
                    avg_return=("return_%", "mean"),
                    avg_vs_spy=("vs_SPY_%", "mean"),
                    beat_spy=("vs_SPY_%", lambda s: (s > 0).mean() * 100))
               .reset_index().round(1)) if not graded.empty else pd.DataFrame()

    return {"detail": detail, "summary": summary,
            "days_span": int(detail["days"].max()) if not detail.empty else 0,
            "n": len(detail)}


if __name__ == "__main__":
    from valuation import build_board
    print("Logging a few test verdicts…")
    rows = build_board(["AAPL", "NVDA", "PFE", "KO"])
    print("logged:", log_verdicts(rows))
    s = score_log()
    if s:
        print(f"\n{s['n']} verdicts · {s['days_span']} days span")
        print("\nSUMMARY by stance:")
        print(s["summary"].to_string(index=False))
        print("\nDETAIL:")
        print(s["detail"].to_string(index=False))
