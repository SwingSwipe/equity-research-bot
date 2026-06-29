# 📈 Equity Research Bot

A transparent, sector-aware stock research tool built in Python — it turns free
public data into an explainable **buy / hold / avoid** view, and keeps score of
whether its own calls actually beat the market.

> **Honest framing first:** this is a research and learning tool, **not an alpha
> engine.** Every factor here is public and widely known; markets are roughly
> efficient. The value is that it's *explainable end to end* — every number and
> every conclusion, including its own limitations, can be defended. See
> [METHODOLOGY.md](METHODOLOGY.md) for the full design.

## What it does

A Streamlit web app with seven views:

| View | What it gives you |
|------|-------------------|
| 🔍 **Stock Research** | Full readout per ticker: an **Undervalued/Fair/Overvalued** verdict + **BUY/HOLD/AVOID** stance with a confidence level, a plain-English "why" summary, valuation breakdown (sector-relative), key ratios, financials, earnings track record, news, and data-quality warnings. |
| 📋 **Watchlist** | Your stocks scored and grouped into Buy leans / Watch closely / Avoid. Click any row to research it. |
| 📡 **Radar** | Catalyst discovery — upcoming earnings, recent surprises, today's movers, IPOs. |
| 🌎 **Market News** | Deduplicated business/market headlines. |
| 📈 **Track Record** | Logs every verdict and grades it **vs. the S&P 500** over time — the honest test of whether it works. |
| 💼 **Portfolio** | A $1,000 paper portfolio of the bot's BUY LEANs, tracked vs. the index. |
| 🔬 **Small-Caps** | A micro-cap **trap detector** (SEC/FINRA red flags), not a "boom finder." |

## How the verdict works (short version)

Valuation is scored through capped, de-correlated *themes* (analyst views,
fundamental multiples, cash), judged **relative to the stock's sector**, then merged
with a separate trend/quality score — gated so an overvalued name is never called a
buy on momentum alone. Broken inputs (negative book value, bank ratios, no-earnings
firms) are flagged, not silently scored. Full detail in [METHODOLOGY.md](METHODOLOGY.md).

## Run it locally

```bash
pip install -r requirements.txt
python -m streamlit run app.py        # opens http://localhost:8501
```

Useful from the terminal too:
```bash
python analyst.py PFE        # bull/bear scorecard for one ticker
python valuation.py NVDA     # full valuation verdict
python 02_screener.py        # multi-factor S&P 500 ranking
python benchmarks.py         # rebuild sector-median multiples
```

## Deploy it (free)

The app is ready for [Streamlit Community Cloud](https://share.streamlit.io):
point it at `app.py` in this folder, and it installs from `requirements.txt`. All
data files use repo-relative paths, so it runs unchanged on Linux. No secrets
required — the optional AI analyst takes a key via the sidebar, never from a file.

## AI analyst (optional)

A written bull/bear thesis via Claude needs an
[Anthropic API key](https://console.anthropic.com/), pasted into the sidebar
(in-session only, never saved). It narrates the computed facts — it does not invent
data or predict prices.

## Project layout

`analyst.py` (data + trend engine) · `valuation.py` (verdict + paper-portfolio
builder) · `benchmarks.py` (sector medians) · `catalysts.py` (radar) ·
`watchlist.py` · `tracker.py` (forward validation) · `portfolio.py` ·
`smallcap.py` · `llm.py` (AI analyst) · `universe.py` (S&P 500 list) ·
`02_screener.py` (factor screen) · `app.py` (UI). Logic is kept separate from the
UI so it can be tested without a browser.

---

*Built from zero as a learning project and equity-research portfolio piece. Not
investment advice.*
