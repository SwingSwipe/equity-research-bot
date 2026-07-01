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


def log_mtime() -> float:
    """Last-modified time of the verdicts log (0.0 if none yet). Lets the app key
    its cache on this, so a headless weekly auto-log auto-busts a stale scorecard."""
    try:
        return os.path.getmtime(LOG_FILE)
    except OSError:
        return 0.0


def load_log(log_file: str = None) -> pd.DataFrame:
    try:
        df = pd.read_csv(log_file or LOG_FILE)
        if not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=LOG_COLS)


def _last_stance_by_ticker(log: pd.DataFrame) -> dict:
    """Most recent logged stance for each ticker (by date). Empty if no log yet."""
    if log.empty:
        return {}
    l = log.copy()
    l["date"] = pd.to_datetime(l["date"])
    l = l.sort_values("date")
    return {tk: grp.iloc[-1]["stance"] for tk, grp in l.groupby("ticker")}


def log_verdicts(board_rows, only_on_change: bool = True, log_file: str = None) -> dict:
    """Record verdicts as a FORWARD track record.

    By default this logs a row for a ticker ONLY when its stance has changed
    since its last logged row (or the ticker is brand new). That's the honest
    way to build a scorecard: one clean forward bet per actual DECISION, instead
    of re-stamping the same standing opinion every week -- which would inflate
    the sample with correlated, overlapping rows and make a tiny, unproven edge
    look statistically solid. Pass only_on_change=False to force a full snapshot.

    log_file lets a separate record (e.g. the pinned gamble watchlist) reuse this
    exact machinery instead of duplicating it. Defaults to the main verdicts log.

    Rows are still deduped on (date, ticker), so running twice in one day is
    harmless. Returns {"logged": rows_written, "unchanged": rows_skipped}.
    """
    path = log_file or LOG_FILE
    today = datetime.today().strftime("%Y-%m-%d")
    last = _last_stance_by_ticker(load_log(path)) if only_on_change else {}

    to_log, unchanged = [], 0
    for r in board_rows:
        price = r.get("Price")
        if price is None or pd.isna(price) or price <= 0:
            continue                              # a priceless row is an ungradeable bet -- skip it
        if only_on_change and last.get(r["Ticker"]) == r["Stance"]:
            unchanged += 1
            continue
        to_log.append({
            "date": today,
            "ticker": r["Ticker"],
            "price": r["Price"],
            "stance": r["Stance"],
            "valuation": r["Valuation"],
            "upside": r.get("Upside %"),
            "trend": r["Trend"],
            "confidence": r["Confidence"],
        })

    if to_log:
        combined = pd.concat([load_log(path), pd.DataFrame(to_log)], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date", "ticker"], keep="last")
        combined.to_csv(path, index=False)
    return {"logged": len(to_log), "unchanged": unchanged}


def score_log(log_file: str = None) -> dict | None:
    """Grade every logged verdict by its return-since vs the S&P 500.

    Both legs -- the stock and SPY -- are measured from the SAME price basis:
    yfinance's split/dividend-adjusted close on the verdict's log date (via
    asof) through to the latest close. We grade the ENTRY from that adjusted
    series rather than from the raw quote we happened to log, so numerator and
    denominator share one adjustment basis; a split or dividend in the window
    can't manufacture a phantom return. The raw logged quote stays in the CSV as
    an audit trail. Verdicts we can't price (unknown ticker, or logged before the
    first available bar) are counted in `ungraded`, never silently dropped.
    """
    log = load_log(log_file)
    if log.empty:
        return None
    log = log.copy()
    log["date"] = pd.to_datetime(log["date"])
    tickers = sorted(log["ticker"].unique().tolist())
    # Buffer the download start a week before the earliest log date so asof()
    # always has a bar on/before it -- otherwise a verdict logged on a weekend or
    # near the data boundary gets a NaN baseline and vanishes from the scorecard.
    start = (log["date"].min() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")

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

    rows, ungraded = [], 0
    for _, r in log.iterrows():
        tk = r["ticker"]
        series = data[tk].dropna() if tk in data.columns else pd.Series(dtype=float)
        entry = series.asof(r["date"]) if not series.empty else None   # adj close on log date
        if entry is None or pd.isna(entry) or entry <= 0:
            ungraded += 1                          # can't price this verdict -- count it, don't hide it
            continue
        cur = series.iloc[-1]
        stock_ret = cur / entry - 1
        spy_at = spy.asof(r["date"])              # SPY level on the same log date
        spy_ret = (spy_now / spy_at - 1) if pd.notna(spy_at) else None
        excess = (stock_ret - spy_ret) if spy_ret is not None else None
        rows.append({
            "date": r["date"].strftime("%Y-%m-%d"),
            "ticker": tk, "stance": r["stance"], "valuation": r["valuation"],
            "trend": r["trend"], "confidence": r["confidence"],
            "logged_price": round(entry, 2), "current_price": round(cur, 2),
            "return_%": round(stock_ret * 100, 1),
            "vs_SPY_%": round(excess * 100, 1) if excess is not None else None,
            # clamp at 0: a verdict logged today, before today's bar publishes,
            # would otherwise read as -1 days old against the last available bar.
            "days": max(0, (last_day - r["date"]).days),
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
            "n": len(detail), "ungraded": ungraded}


# ---------------------------------------------------------------------------
# Pinned gamble watchlist -- a SEPARATE forward record for speculative names you
# want to follow deliberately, kept apart from the main verdict log so gambles
# don't muddy the "is the disciplined process working" signal. Same engine, same
# honest vs-SPY grading; just a different file.
# ---------------------------------------------------------------------------
GWATCH_LOG = os.path.join(os.path.dirname(__file__), "gamble_watch_log.csv")


def gwatch_mtime() -> float:
    try:
        return os.path.getmtime(GWATCH_LOG)
    except OSError:
        return 0.0


def log_gamble_watch(board_rows) -> dict:
    """Forward-log your pinned gamble names (change-only), into their own log."""
    return log_verdicts(board_rows, log_file=GWATCH_LOG)


def score_gamble_watch() -> dict | None:
    """Grade the pinned gamble names' returns-since vs SPY, same as score_log."""
    return score_log(log_file=GWATCH_LOG)


GAMBLE_LOG = os.path.join(os.path.dirname(__file__), "gamble_log.csv")


def gamble_mtime() -> float:
    """Last-modified time of the gamble log (0.0 if none yet) -- for cache keying."""
    try:
        return os.path.getmtime(GAMBLE_LOG)
    except OSError:
        return 0.0


def log_gamble(sc_df) -> int:
    """Log today's Gamble-tab calls (date, ticker, price, call) to grade later."""
    today = datetime.today().strftime("%Y-%m-%d")
    new = pd.DataFrame([{"date": today, "ticker": r["Symbol"],
                         "price": r["Price"], "call": r["Call"]}
                        for _, r in sc_df.iterrows()])
    try:
        old = pd.read_csv(GAMBLE_LOG)
    except Exception:
        old = pd.DataFrame(columns=["date", "ticker", "price", "call"])
    combined = pd.concat([old, new], ignore_index=True).drop_duplicates(
        subset=["date", "ticker"], keep="last")
    combined.to_csv(GAMBLE_LOG, index=False)
    return len(new)


def score_gamble() -> dict | None:
    """Grade logged Gamble calls: a bullish call (SPEC-LONG/MOMENTUM) 'hits' if the
    stock rose; a bearish call (FADE/AVOID) 'hits' if it fell. NO-EDGE = no bet."""
    try:
        log = pd.read_csv(GAMBLE_LOG)
    except Exception:
        return None
    if log.empty:
        return None
    from portfolio import _current_prices
    prices = _current_prices(sorted(log["ticker"].astype(str).unique()))

    rows = []
    for _, r in log.iterrows():
        cur = prices.get(str(r["ticker"]))
        if cur is None or not r["price"]:
            continue
        ret = cur / r["price"] - 1
        call = str(r["call"])
        bull = ("SPEC-LONG" in call) or ("MOMENTUM" in call)
        bear = ("FADE" in call) or ("AVOID" in call)
        hit = (ret > 0) if bull else (ret < 0) if bear else None
        rows.append({"date": r["date"], "ticker": r["ticker"], "call": call,
                     "return_%": round(ret * 100, 1), "hit": hit})
    detail = pd.DataFrame(rows)
    if detail.empty:
        return None
    graded = detail[detail["hit"].notna()]
    summary = (graded.groupby("call").agg(
        n=("ticker", "size"), avg_return=("return_%", "mean"),
        hit_rate=("hit", lambda s: s.sum() / len(s) * 100)).reset_index().round(1)
        if not graded.empty else pd.DataFrame())
    return {"detail": detail, "summary": summary, "n": len(detail)}


if __name__ == "__main__":
    from valuation import build_board
    print("Logging a few test verdicts…")
    rows = build_board(["AAPL", "NVDA", "PFE", "KO"])
    res = log_verdicts(rows)
    print(f"logged: {res['logged']} new/changed, {res['unchanged']} unchanged")
    s = score_log()
    if s:
        print(f"\n{s['n']} verdicts · {s['days_span']} days span")
        print("\nSUMMARY by stance:")
        print(s["summary"].to_string(index=False))
        print("\nDETAIL:")
        print(s["detail"].to_string(index=False))
