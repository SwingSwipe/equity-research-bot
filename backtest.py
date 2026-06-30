"""
backtest.py  --  does a momentum factor edge actually exist? (honest version)

THE QUESTION: if you'd ranked the universe by 12-month price momentum each month,
held the top names, rebalanced, and paid realistic trading costs -- would you have
beaten just buying the S&P 500? This is the test the whole project was built to run.

WHY ONLY MOMENTUM (and not the full fundamental verdict):
  Prices are point-in-time -- the price on 2019-03-01 really was that price, so
  ranking by past returns uses no future information. That's a CLEAN backtest.
  Fundamentals are NOT point-in-time here: yfinance serves *today's* P/E, ROE, etc.,
  so backtesting the valuation verdict would be lookahead cheating. We refuse to.

THE CAVEATS (stated, not buried -- this is the whole point):
  * SURVIVORSHIP BIAS: the universe is TODAY's S&P 500 members. Companies that went
    bankrupt or were deleted are missing, which INFLATES results. A real edge would
    need point-in-time membership (paid data). Treat any outperformance with suspicion.
  * Costs are modeled (bps per trade on turnover) but slippage/taxes are simplified.
  * One strategy over one period proves little. This is a learning exercise.

Run:  python backtest.py
Output: printed stats + an equity-curve chart (backtest_equity.png).
"""

import numpy as np
import pandas as pd
import yfinance as yf

from universe import get_sp500

# ---- knobs -----------------------------------------------------------------
LIMIT = 150          # universe size (None = full S&P 500, slower). Sampled for speed.
START = "2017-01-01"
TOP_N = 20           # hold the top-N momentum names, equal-weight
LOOKBACK_M = 12      # momentum = return over the past 12 months...
SKIP_M = 1           # ...skipping the most recent month (standard 12-1 momentum)
COST_BPS = 10        # 10 bps (0.10%) per trade, charged on turnover


def _load_prices(tickers):
    """Daily closes for the universe + SPY, as a month-end price table."""
    data = yf.download(tickers + ["SPY"], start=START, progress=False, auto_adjust=True)["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame()
    monthly = data.resample("ME").last()          # month-end prices
    return monthly


def run_backtest():
    sp = get_sp500()
    tickers = sp["Ticker"].tolist()
    if LIMIT:
        tickers = tickers[:LIMIT]

    print(f"Downloading {len(tickers)} stocks + SPY since {START} ...")
    px = _load_prices(tickers)
    rets = px.pct_change()                         # monthly returns
    spy_ret = rets["SPY"]
    stock_px = px.drop(columns=["SPY"], errors="ignore")

    dates = px.index
    strat_rets, bench_rets, prev_holdings = [], [], set()
    first = LOOKBACK_M + SKIP_M                     # need this much history before trading

    for i in range(first, len(dates) - 1):
        t = dates[i]
        # momentum known AT t: return from (t-12m) to (t-1m), skipping last month
        past = stock_px.iloc[i - LOOKBACK_M - SKIP_M]
        recent = stock_px.iloc[i - SKIP_M]
        mom = (recent / past - 1).dropna()
        if len(mom) < TOP_N:
            continue
        holdings = set(mom.sort_values(ascending=False).head(TOP_N).index)

        # next month's return = equal-weight mean of held names (t -> t+1)
        nxt = rets.iloc[i + 1]
        held_ret = nxt[list(holdings)].mean()

        # trading cost on turnover (names changed since last month)
        turnover = len(holdings.symmetric_difference(prev_holdings)) / (2 * TOP_N)
        cost = turnover * (COST_BPS / 10000)
        strat_rets.append(held_ret - cost)
        bench_rets.append(spy_ret.iloc[i + 1])
        prev_holdings = holdings

    s = pd.Series(strat_rets, index=dates[first + 1: first + 1 + len(strat_rets)]).dropna()
    b = pd.Series(bench_rets, index=s.index[:len(bench_rets)]).reindex(s.index).dropna()
    s = s.reindex(b.index)
    return s, b


def _stats(r):
    n = len(r)
    total = (1 + r).prod() - 1
    ann = (1 + total) ** (12 / n) - 1 if n else 0
    vol = r.std() * np.sqrt(12)
    sharpe = (r.mean() * 12) / vol if vol else 0
    curve = (1 + r).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    return {"total": total, "ann": ann, "vol": vol, "sharpe": sharpe, "maxdd": dd}


def main():
    strat, bench = run_backtest()
    ss, bs = _stats(strat), _stats(bench)
    months = len(strat)

    print(f"\n=== MOMENTUM BACKTEST ({months} months, top {TOP_N}, {COST_BPS}bps costs) ===")
    print(f"{'':16}{'Momentum':>12}{'S&P 500':>12}")
    print(f"{'Total return':16}{ss['total']*100:>11.1f}%{bs['total']*100:>11.1f}%")
    print(f"{'Annualized':16}{ss['ann']*100:>11.1f}%{bs['ann']*100:>11.1f}%")
    print(f"{'Volatility':16}{ss['vol']*100:>11.1f}%{bs['vol']*100:>11.1f}%")
    print(f"{'Sharpe':16}{ss['sharpe']:>12.2f}{bs['sharpe']:>12.2f}")
    print(f"{'Max drawdown':16}{ss['maxdd']*100:>11.1f}%{bs['maxdd']*100:>11.1f}%")

    edge = ss["ann"] - bs["ann"]
    print(f"\n>>> Momentum {'BEAT' if edge > 0 else 'LAGGED'} the market by "
          f"{edge*100:+.1f}%/yr (before the survivorship caveat below).")
    print("\n*** SURVIVORSHIP WARNING: universe = TODAY's S&P 500 (the survivors). "
          "This INFLATES the result. A real edge needs point-in-time membership. "
          "Don't trade on this -- it's a learning backtest. ***")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        (1 + strat).cumprod().plot(label="Momentum (top 20)")
        (1 + bench).cumprod().plot(label="S&P 500 (SPY)")
        plt.title("Momentum vs S&P 500 — $1 growth (survivorship-biased)")
        plt.legend(); plt.ylabel("Growth of $1"); plt.tight_layout()
        plt.savefig("backtest_equity.png", dpi=110)
        print("\nSaved chart -> backtest_equity.png")
    except Exception as e:
        print("(chart skipped:", e, ")")


if __name__ == "__main__":
    main()
