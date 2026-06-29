# Methodology

How the research bot turns public data into a transparent buy / hold / avoid view —
and, just as importantly, where it stops being trustworthy.

## Design principle

Every number is traceable and every conclusion is explainable. There is no black
box and no machine-learning oracle. The goal is a **defensible second opinion**,
not a price prediction. The whole system is built so that, in an interview, every
output can be defended from first principles.

## 1. Data layer (`analyst.py`)

A single `get_snapshot(ticker)` call assembles everything from yfinance: live price
and moving averages, 12-month price history, valuation multiples (P/E, forward P/E,
P/B, P/S, PEG, EV/EBITDA), quality metrics (ROE, margins, debt/equity), growth,
analyst price targets and ratings, recent news, earnings surprise history, and the
income statement. A `light=True` mode skips the slow extras for bulk screening.

## 2. The verdict (`valuation.py`)

**Valuation** is scored through independent lenses grouped into three *themes*:

- **Analyst** — price-target upside and consensus rating
- **Multiples** — PEG, forward-vs-trailing P/E, sector-relative P/E, sector-relative EV/EBITDA
- **Cash** — free-cash-flow yield

Two deliberate design choices make this more honest than a naïve screen:

1. **Sector-relative valuation.** "P/E 25" is cheap for software and expensive for a
   utility, so multiples are compared to the stock's *sector median* (computed in
   `benchmarks.py`), not to one-size-fits-all thresholds.
2. **Signal de-correlation.** PEG, forward P/E, sector P/E and EV/EBITDA all measure
   the same idea — "cheap on fundamentals." Each *theme* is **capped**, so four
   correlated signals agreeing cannot masquerade as four independent units of
   conviction. This prevents valuation from silently dominating the verdict.

The theme scores sum to a verdict — **Undervalued / Fairly Valued / Overvalued** —
plus a **confidence** level that requires genuine conviction (a clear score *and*
enough independent signals *and* real analyst coverage). A borderline read is never
labeled "High confidence."

**Trend & quality** (`compute_bias`) is scored separately and only on price action
(vs. 50/200-day averages, 12-month momentum, 52-week range) plus ROE and growth —
valuation is intentionally excluded here to avoid double-counting.

**The overall stance** merges valuation and trend, *gated* so that an overvalued
name is never called a buy on momentum alone, and a value-trap (cheap but in a
downtrend) is flagged rather than bought.

## 3. Data-sanity guards

A verdict is only as good as its inputs, so broken inputs are detected and either
skipped or flagged: financial-sector companies skip EV/EBITDA and FCF (meaningless
for banks); negative book value, no-earnings firms, buyback-flattered ROE, extreme
leverage, and thin sector samples all raise visible warnings.

## 4. Screening & discovery

- **Multi-factor screener** (`02_screener.py`) ranks the S&P 500 on cross-sectional,
  winsorized z-scores across Value / Quality / Growth / Momentum.
- **Radar** surfaces catalysts (earnings, movers, IPOs).
- **Small-Cap Explorer** triages micro-caps against SEC/FINRA fraud red flags — a
  *trap detector*, explicitly not a "boom finder."

## 5. Validation — the part that matters most

- **Track Record** logs every verdict with date and price and later grades it against
  the S&P 500 (forward-only, so no lookahead bias).
- **Paper Portfolio** equal-weights $1,000 across the bot's BUY LEANs and tracks it
  vs. the index — paper trading the bot's process.

## Honest limitations (stated, not buried)

- **Not an edge.** Every factor here is public and widely known; markets are roughly
  efficient. This organizes evidence; it does not beat the market.
- **Survivorship bias** — screens run on *today's* index members, ignoring delisted
  failures. This inflates any naïve backtest; present-day screening is unaffected.
- **Lookahead bias** — yfinance serves *current* fundamentals, not point-in-time
  data, so rigorous *fundamental* backtesting isn't possible. Prices are clean;
  validation is therefore forward-only.
- **Single data source** — everything flows through yfinance, which is free but
  occasionally wrong or missing, especially for small caps.
- **Not investment advice.**

The value of the project is not a winning strategy. It is a transparent, sector-aware,
self-validating research tool whose every claim — including its own limits — can be
defended.
