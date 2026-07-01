"""
portfolio.py  --  a $1,000 PAPER portfolio driven purely by the bot's verdicts.

This is paper trading: fake money, real prices, honest scorekeeping. We let the
bot pick (the BUY LEANs), split the cash equally across them, record entry
prices and the S&P 500's level that day, then re-value it whenever we like and
compare to just buying the market.

WHY EQUAL WEIGHT: sizing positions by "conviction" feels smart but it's the same
overfitting we've avoided all along. Equal weight is the disciplined default --
it makes no claim we can't back up.

HONEST LIMITS:
  * A handful of names over a few weeks proves nothing -- it's a demo of process,
    not evidence of edge. Judge it over many names and long windows.
  * No trading costs/taxes modeled (on $1,000 paper they're negligible anyway).
  * Picks are only as good as the bot, which is an unproven second opinion.
"""

import json
import os
from datetime import datetime

import pandas as pd
import yfinance as yf

from valuation import build_board

PORT_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")       # public demo
MY_PORT_FILE = os.path.join(os.path.dirname(__file__), "my_portfolio.json")  # personal (gitignored)


def _finnhub_quote(symbol):
    try:
        from provider import _get, available
        if available():
            q = _get("quote", symbol=symbol)
            if q and q.get("c"):
                return float(q["c"])
    except Exception:
        pass
    return None


def _spy_price():
    try:
        return float(yf.Ticker("SPY").fast_info["last_price"])
    except Exception:
        return _finnhub_quote("SPY")


def _current_prices(symbols) -> dict:
    """Current price per symbol: yfinance first, Finnhub fallback (cloud-reliable)."""
    symbols = list(symbols)
    prices = {}
    try:
        data = yf.download(symbols, period="5d", progress=False)["Close"]
        if isinstance(data, pd.Series):
            data = data.to_frame()
        for s in symbols:
            try:
                v = float(data[s].dropna().iloc[-1])
                if v > 0:
                    prices[s] = v
            except Exception:
                pass
    except Exception:
        pass
    for s in [s for s in symbols if s not in prices]:      # Finnhub for any missing
        q = _finnhub_quote(s)
        if q:
            prices[s] = q
    return prices


def load_portfolio() -> dict | None:
    try:
        with open(PORT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def load_my_portfolio() -> dict | None:
    """Your PERSONAL portfolio (separate file, gitignored, never public)."""
    try:
        with open(MY_PORT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_my_portfolio(port: dict):
    with open(MY_PORT_FILE, "w") as f:
        json.dump(port, f, indent=2)


def _save(port):
    with open(PORT_FILE, "w") as f:
        json.dump(port, f, indent=2)


def save_portfolio(port: dict):
    """Persist a portfolio to disk (used by the local app's Save button only)."""
    _save(port)


def build_portfolio(tickers, capital: float = 1000.0, max_names: int = 8,
                    save: bool = True) -> dict | None:
    """Pick the bot's BUY LEANs, equal-weight `capital` across the top names.
    save=False returns the dict without writing to disk (used by the web app so
    each visitor's portfolio stays private to their session)."""
    board = build_board(list(tickers))
    if not board:
        return None
    df = pd.DataFrame(board)
    buys = (df[df["Stance"] == "BUY LEAN"]
            .sort_values("_score", ascending=False)
            .head(max_names))
    if buys.empty:
        return None

    alloc = capital / len(buys)
    today = datetime.today().strftime("%Y-%m-%d")
    holdings = []
    for _, r in buys.iterrows():
        price = float(r["Price"])
        holdings.append({
            "ticker": r["Ticker"], "name": r["Name"],
            "entry_date": today, "entry_price": round(price, 2),
            "shares": round(alloc / price, 4), "alloc": round(alloc, 2),
            "valuation": r["Valuation"], "trend": r["Trend"],
            "confidence": r["Confidence"],
            "upside_at_entry": r.get("Upside %"),
        })

    port = {"created": today, "capital": capital,
            "spy_entry": _spy_price(), "holdings": holdings}
    if save:
        _save(port)
    return port


def build_custom_portfolio(tickers, capital: float = 1000.0,
                           save: bool = False) -> dict | None:
    """Equal-weight `capital` across EXACTLY the tickers given (no bot filtering).
    Used when the user picks their own stocks."""
    prices = _current_prices(tickers)
    valid = [(tk, prices[tk]) for tk in tickers if prices.get(tk)]
    if not valid:
        return None

    alloc = capital / len(valid)
    today = datetime.today().strftime("%Y-%m-%d")
    holdings = [{
        "ticker": tk, "name": tk, "entry_date": today,
        "entry_price": round(p, 2), "shares": round(alloc / p, 4),
        "alloc": round(alloc, 2), "valuation": "—", "trend": "—",
        "confidence": "—", "upside_at_entry": None,
    } for tk, p in valid]
    port = {"created": today, "capital": capital,
            "spy_entry": _spy_price(), "holdings": holdings}
    if save:
        _save(port)
    return port


def value_portfolio(port: dict = None) -> dict | None:
    """Re-price the portfolio today and compare to the S&P 500."""
    port = port or load_portfolio()
    if not port or not port.get("holdings"):
        return None

    tickers = [h["ticker"] for h in port["holdings"]]
    prices = _current_prices(tickers + ["SPY"])

    rows, total_value, total_cost, unpriced = [], 0.0, 0.0, []
    for h in port["holdings"]:
        cur = prices.get(h["ticker"])
        total_cost += h["alloc"]                  # full capital always counts, priced or not
        if cur is None:
            # Couldn't fetch a price. Don't let the holding silently vanish (that
            # would shrink the portfolio and misstate the return over the survivors).
            # Hold it flat at its entry and flag it so the number stays honest.
            unpriced.append(h["ticker"])
            total_value += h["alloc"]
            rows.append({
                "Ticker": h["ticker"], "Entry": h["entry_price"], "Now": None,
                "Shares": h["shares"], "Value": round(h["alloc"], 2),
                "Return %": None, "P&L $": None,
                "Valuation": h["valuation"], "Conf": h["confidence"],
            })
            continue
        value = h["shares"] * cur
        total_value += value
        rows.append({
            "Ticker": h["ticker"], "Entry": h["entry_price"], "Now": round(cur, 2),
            "Shares": h["shares"], "Value": round(value, 2),
            "Return %": round((cur / h["entry_price"] - 1) * 100, 1),
            "P&L $": round(value - h["alloc"], 2),
            "Valuation": h["valuation"], "Conf": h["confidence"],
        })

    port_ret = (total_value / total_cost - 1) if total_cost else 0.0
    spy_now, spy_entry = prices.get("SPY"), port.get("spy_entry")
    spy_ret = (spy_now / spy_entry - 1) if (spy_now and spy_entry) else None
    excess = (port_ret - spy_ret) if spy_ret is not None else None

    return {
        "detail": pd.DataFrame(rows),
        "total_value": round(total_value, 2),
        "total_return_pct": round(port_ret * 100, 2),
        "spy_return_pct": round(spy_ret * 100, 2) if spy_ret is not None else None,
        "excess_pct": round(excess * 100, 2) if excess is not None else None,
        "created": port.get("created"), "capital": port.get("capital", 1000),
        "unpriced": unpriced,      # holdings held flat because no price could be fetched
    }


if __name__ == "__main__":
    from watchlist import load_watchlist
    print("Building $1,000 paper portfolio from the watchlist BUY LEANs…")
    port = build_portfolio(load_watchlist())
    if not port:
        print("No BUY LEANs found.")
    else:
        v = value_portfolio(port)
        print(f"\nCreated {port['created']} · {len(port['holdings'])} holdings · "
              f"SPY entry {port['spy_entry']}")
        print(v["detail"].to_string(index=False))
        print(f"\nValue ${v['total_value']} · return {v['total_return_pct']}% · "
              f"SPY {v['spy_return_pct']}% · excess {v['excess_pct']}%")
