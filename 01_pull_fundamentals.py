"""
Step 1 of the equity research bot: pull fundamental data for a small universe.

What this does:
  - Defines a small, sector-diversified universe of stocks.
  - Asks yfinance for each company's fundamental metrics.
  - Puts them into one clean pandas table and prints it.

Run it with:  python 01_pull_fundamentals.py
"""

import time
import yfinance as yf
import pandas as pd

# ---------------------------------------------------------------------------
# 1. OUR UNIVERSE
# A "universe" is just the list of tickers we're allowed to consider.
# We start small and sector-diverse so we can eyeball every number.
# ---------------------------------------------------------------------------
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL",   # Tech
    "AMZN", "HD", "MCD", "KO",         # Consumer
    "JPM", "BAC", "V",                 # Financials
    "JNJ", "UNH", "PFE",               # Healthcare
    "XOM", "CVX",                      # Energy
    "CAT",                             # Industrials
]

# ---------------------------------------------------------------------------
# 2. WHICH FUNDAMENTAL FIELDS WE WANT
# yfinance returns a big dict per stock (.info). These are the keys we care
# about for now: value + quality + growth factors. Momentum comes later
# (it's computed from prices, not pulled as a field).
# The dict's keys are yfinance's names; the values are friendlier labels.
# ---------------------------------------------------------------------------
FIELDS = {
    "sector": "Sector",
    "marketCap": "MarketCap",
    "trailingPE": "P/E",
    "priceToBook": "P/B",
    "priceToSalesTrailing12Months": "P/S",
    "returnOnEquity": "ROE",
    "profitMargins": "NetMargin",
    "debtToEquity": "Debt/Equity",
    "revenueGrowth": "RevGrowth",
    "earningsGrowth": "EarnGrowth",
}


def pull_one(ticker: str) -> dict:
    """Pull the fundamental fields for a single ticker into a plain dict."""
    info = yf.Ticker(ticker).info          # one network call -> big dict
    row = {"Ticker": ticker}
    for yf_key, nice_name in FIELDS.items():
        row[nice_name] = info.get(yf_key)  # .get() returns None if missing
    return row


def main() -> None:
    rows = []
    for ticker in UNIVERSE:
        print(f"Pulling {ticker} ...")
        try:
            rows.append(pull_one(ticker))
        except Exception as e:                 # don't let one bad ticker kill the run
            print(f"  !! failed on {ticker}: {e}")
        time.sleep(0.4)                        # be polite to the free API

    # Build the table: one row per stock, one column per metric.
    df = pd.DataFrame(rows).set_index("Ticker")

    # Make the printout readable instead of scientific notation.
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)

    print("\n=== FUNDAMENTALS ===")
    print(df)

    # Save it so the next script can read it without re-pulling.
    df.to_csv("fundamentals.csv")
    print("\nSaved -> fundamentals.csv")


if __name__ == "__main__":
    main()
