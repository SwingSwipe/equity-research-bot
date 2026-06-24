"""
universe.py  --  where our list of stocks to screen comes from.

Instead of hand-typing tickers, we scrape the live S&P 500 membership table
from Wikipedia. pandas.read_html() reads every <table> on a web page straight
into DataFrames -- one line, no manual parsing.

SURVIVORSHIP-BIAS WARNING (say it every time): this is TODAY's membership.
Companies that were deleted (bankruptcies, takeovers) are gone from this list.
Fine for "what looks good to screen now"; it will INFLATE any backtest, because
you'd be testing only on the survivors. We handle that honestly when we backtest.
"""

import io

import pandas as pd
import requests

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Wikipedia rejects Python's default user-agent (403 Forbidden), so we send a
# normal browser one. This is standard, polite scraping -- identify yourself.
HEADERS = {"User-Agent": "Mozilla/5.0 (research-bot; educational use)"}


def get_sp500() -> pd.DataFrame:
    """Return a DataFrame of current S&P 500 members: Ticker + Sector + Name."""
    html = requests.get(SP500_URL, headers=HEADERS, timeout=20).text
    # read_html returns a LIST of every table on the page; the first is the one we want.
    tables = pd.read_html(io.StringIO(html))
    df = tables[0]

    out = pd.DataFrame({
        "Ticker": df["Symbol"].str.replace(".", "-", regex=False),  # BRK.B -> BRK-B for yfinance
        "Name": df["Security"],
        "Sector": df["GICS Sector"],
    })
    return out


if __name__ == "__main__":
    sp = get_sp500()
    print(f"Pulled {len(sp)} S&P 500 members.\n")
    print(sp.head(10).to_string(index=False))
    print("\nSector counts:")
    print(sp["Sector"].value_counts().to_string())
