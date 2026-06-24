# 📈 Equity Research Bot

A two-layer stock research tool built in Python:

1. **Single-stock research app** (Streamlit) — type a ticker and get live price, a
   price chart with moving averages, recent news, the next earnings date, and a
   **transparent long/short lean** built from a weighted scorecard of signals.
2. **Multi-factor screener** — ranks a universe of stocks on a composite of
   **Value, Quality, Growth, and Momentum** factors using cross-sectional z-scores.
3. **AI analyst layer** (optional) — Claude writes a balanced bull/bear research
   note grounded *only* in the computed facts and headlines.

## Honest framing (read this first)

This is a **research and learning tool, not an alpha engine.** Every factor here
(value, quality, growth, momentum) is public and widely known, so none of it is a
secret edge — markets are roughly efficient. The value of this project is that it is
**explainable end to end**: every number and every conclusion can be traced and
defended. A black-box "BUY" button you can't explain is worth less than a
transparent lean you can.

### Known limitations (deliberately stated)

- **Survivorship bias** — the universe is *today's* index members, which ignores
  companies that went bankrupt or were delisted. This inflates any naive backtest,
  so the screener ranks "what looks good now"; it does **not** claim these names beat
  the market. A rigorous backtest (with this caveat handled) is future work.
- **Lookahead bias** — yfinance serves *current* fundamentals, not point-in-time
  data. Daily prices are clean, but historical *fundamental* backtesting is limited
  (using restated financials is cheating). Acknowledged, not hidden.
- **Equal factor weights** — chosen on purpose. Tuning weights until the output
  "looks right" is overfitting.

## Project layout

| File | Role |
|------|------|
| `analyst.py` | Engine: pull one stock's data (`get_snapshot`) + build the bias scorecard (`compute_bias`). No UI — testable from the terminal. |
| `app.py` | Streamlit web UI. Presentation only; calls the engine. |
| `llm.py` | AI analyst layer — turns the computed facts into a written thesis via Claude. |
| `02_screener.py` | Multi-factor screener: z-score ranking across the universe. |
| `01_pull_fundamentals.py` | Standalone fundamentals puller (first build step). |

The split between **logic** (`analyst.py`) and **UI** (`app.py`) is intentional:
logic you can test without launching a browser is logic you can trust.

## Setup

```bash
pip install -r requirements.txt
```

## Run

**The web app:**
```bash
python -m streamlit run app.py
```
Then open the URL it prints and type a ticker (e.g. `AAPL`).

**The screener:**
```bash
python 02_screener.py        # prints a ranked watchlist, saves ranked_watchlist.csv
```

**The engine, straight from the terminal:**
```bash
python analyst.py PFE        # prints the bull/bear scorecard for one ticker
```

## AI analyst (optional)

The written thesis needs an [Anthropic API key](https://console.anthropic.com/).
Paste it into the app's sidebar (it stays in-session, never written to disk).
The model only narrates the facts the engine computes — it does not invent data
or predict prices.

## Roadmap

- [ ] Winsorize factor z-scores (cap outliers like NVDA's growth)
- [ ] Rank within-sector where factors aren't comparable across sectors (e.g. bank leverage)
- [ ] Expand the universe to the full S&P 500
- [ ] A careful backtest — with transaction costs, rebalancing, and the survivorship caveat stated

---

*Built as a learning project and equity-research portfolio piece. Not investment advice.*
