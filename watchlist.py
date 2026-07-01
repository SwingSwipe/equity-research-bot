"""
watchlist.py  --  load & save your personal list of tickers.

This is your first taste of PERSISTENCE: writing data to a file so it survives
the program closing. We use JSON -- a simple text format that maps cleanly to a
Python list. load_watchlist() reads it back; save_watchlist() writes it out.

The file (watchlist.json) is gitignored -- it's your personal data, not code.
"""

import json
import os

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")

# A sensible starting watchlist if you haven't saved your own yet.
DEFAULT = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "V", "UNH",
    "XOM", "JNJ", "WMT", "PG", "HD", "KO", "PFE", "DIS", "NKE", "BAC",
]


def load_watchlist() -> list:
    """Read the saved watchlist, or fall back to the default."""
    try:
        with open(WATCHLIST_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return [str(t).upper() for t in data]
    except Exception:
        pass                                   # no file yet, or unreadable
    return list(DEFAULT)


def save_watchlist(tickers) -> bool:
    """Write the watchlist to disk. Returns True on success."""
    try:
        cleaned = [t.strip().upper() for t in tickers if t and t.strip()]
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(cleaned, f, indent=2)
        return True
    except Exception:
        return False


GAMBLE_WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "gamble_watchlist.json")


def load_gamble_watchlist() -> list:
    """Your PINNED speculative names -- a separate list from the main watchlist,
    so gambles you follow don't get graded next to the disciplined picks. Starts
    empty; you add to it deliberately."""
    try:
        with open(GAMBLE_WATCHLIST_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(t).upper() for t in data]
    except Exception:
        pass
    return []


def save_gamble_watchlist(tickers) -> bool:
    try:
        cleaned = []
        for t in tickers:
            t = str(t).strip().upper()
            if t and t not in cleaned:
                cleaned.append(t)
        with open(GAMBLE_WATCHLIST_FILE, "w") as f:
            json.dump(cleaned, f, indent=2)
        return True
    except Exception:
        return False


def parse_tickers(text: str) -> list:
    """Turn a free-text box ('AAPL, msft  TSLA') into a clean ticker list."""
    raw = text.replace("\n", ",").replace(" ", ",").split(",")
    seen, out = set(), []
    for t in raw:
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
