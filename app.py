"""
app.py  --  the web UI for the stock research bot.

Run it with:   python -m streamlit run app.py

This file is ONLY presentation. All the thinking lives in analyst.py /
catalysts.py. Streamlit re-runs this whole script top-to-bottom on every
interaction -- your script *is* the page.

NAVIGATION NOTE: we use a segmented_control (not st.tabs) for the three views,
because st.tabs can't be switched from code. With segmented_control the active
view lives in st.session_state, so clicking a ticker on the Radar can set the
view to "Stock Research" and load that ticker -- the whole point of this build.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from analyst import get_snapshot, compute_bias, get_market_news, num, pct
from valuation import value_verdict, overall_verdict, build_board, why_summary
from catalysts import (get_movers, get_upcoming_earnings,
                       get_recent_surprises, get_ipos)
from watchlist import load_watchlist, save_watchlist, parse_tickers
from tracker import log_verdicts, score_log
from llm import write_thesis, DEFAULT_MODEL

st.set_page_config(page_title="Stock Research Bot", page_icon="📈", layout="wide")

VIEWS = ["🔍 Stock Research", "📋 Watchlist", "📡 Radar",
         "🌎 Market News", "📈 Track Record"]


# ---------------------------------------------------------------------------
# DATA LOADERS (cached). Quotes are ~15 min delayed on free Yahoo data; the
# cache re-pulls every 5 min, and the sidebar Refresh button forces it.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load(ticker: str):
    snap = get_snapshot(ticker)
    bias = compute_bias(snap)                 # momentum + quality scorecard
    val = value_verdict(snap)                 # under/over-valued verdict
    overall = overall_verdict(snap, bias, val)  # merged buy/hold/avoid stance
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return snap, bias, val, overall, fetched_at


@st.cache_data(ttl=300, show_spinner=False)
def load_market_news():
    return get_market_news(limit=25), datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@st.cache_data(ttl=300, show_spinner=False)
def load_board(tickers: tuple):
    """Run the full verdict engine across a watchlist (tuple so it's cacheable)."""
    return build_board(list(tickers)), datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@st.cache_data(ttl=600, show_spinner=False)
def score_tracker():
    return score_log()


@st.cache_data(ttl=300, show_spinner=False)
def load_radar():
    return {
        "gainers": get_movers("day_gainers", 15),
        "losers": get_movers("day_losers", 15),
        "actives": get_movers("most_actives", 15),
        "earnings": get_upcoming_earnings(days=7),
        "surprises": get_recent_surprises(days=3),
        "ipos": get_ipos(),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


LEAN_COLORS = {
    "LONG": "#16a34a", "LEAN LONG": "#4ade80", "NEUTRAL": "#9ca3af",
    "LEAN SHORT": "#f87171", "SHORT": "#dc2626",
}
STANCE_COLORS = {"BUY LEAN": "#16a34a", "HOLD / NEUTRAL": "#9ca3af", "AVOID LEAN": "#dc2626"}
VERDICT_COLORS = {"Undervalued": "#16a34a", "Fairly Valued": "#9ca3af", "Overvalued": "#dc2626"}
CONF_COLORS = {"High": "#16a34a", "Medium": "#d97706", "Low": "#9ca3af"}


def news_item(n):
    title = n["title"] or "(untitled)"
    meta = " · ".join(x for x in [n.get("publisher"), (n.get("date") or "")[:10]] if x)
    link = f"[{title}]({n['url']})" if n.get("url") else f"**{title}**"
    st.markdown(f"**{link}**  \n<span style='color:#888'>{meta}</span>",
                unsafe_allow_html=True)
    if n.get("summary"):
        st.caption(n["summary"])


def go_to_research(ticker: str):
    """Queue a jump to the Stock Research view with this ticker loaded.

    We can't set the 'view'/'ticker' widget state directly here (Streamlit
    forbids changing a widget's value after it's been created this run). So we
    stash the request in *pending* keys; the top of the next run applies them
    BEFORE the widgets are built. Bumping nav_token gives the Radar tables fresh
    keys so their old row-selection doesn't immediately re-trigger this jump.
    """
    st.session_state._pending_ticker = ticker
    st.session_state._pending_view = VIEWS[0]
    st.session_state.nav_token += 1
    st.rerun()


def open_picker(tickers, key):
    """A dead-simple, always-works dropdown to open a ticker in Stock Research.
    Used alongside the clickable tables so navigation never feels broken."""
    options = ["— pick a stock —"] + list(dict.fromkeys(tickers))   # dedupe, keep order

    def _go():
        sym = st.session_state.get(key)
        if sym and not sym.startswith("—"):
            st.session_state._pending_ticker = sym
            st.session_state._pending_view = VIEWS[0]
            st.session_state.nav_token += 1
            st.session_state[key] = options[0]            # reset so it's reusable

    st.selectbox("🔍 Open a stock in Research", options, key=key, on_change=_go)


def selectable_table(df, base_key, column_config=None, symbol_col="Symbol"):
    """Show a dataframe whose rows are clickable; return the clicked ticker."""
    if df is None or df.empty:
        st.caption("None right now.")
        return None
    key = f"{base_key}_{st.session_state.nav_token}"     # fresh key after a jump
    event = st.dataframe(
        df, key=key, on_select="rerun", selection_mode="single-row",
        hide_index=True, use_container_width=True, column_config=column_config or {},
    )
    rows = event.selection.rows
    return str(df.iloc[rows[0]][symbol_col]) if rows else None


# ---------------------------------------------------------------------------
# SESSION STATE  +  apply any pending navigation BEFORE widgets are created
# ---------------------------------------------------------------------------
st.session_state.setdefault("ticker", "AAPL")
st.session_state.setdefault("view", VIEWS[0])
st.session_state.setdefault("nav_token", 0)

if "_pending_ticker" in st.session_state:
    st.session_state.ticker = st.session_state.pop("_pending_ticker")
if "_pending_view" in st.session_state:
    st.session_state.view = st.session_state.pop("_pending_view")


# ---- sidebar: refresh + optional Anthropic API key -------------------------
with st.sidebar:
    if st.button("🔄 Refresh data", use_container_width=True):
        load.clear()
        load_market_news.clear()
        load_radar.clear()
        st.rerun()
    st.caption("Data is live from Yahoo Finance (quotes ~15 min delayed on the "
               "free feed). Auto-refreshes every 5 min; click above to force it.")

    st.divider()
    st.markdown("### 🤖 AI Analyst (optional)")
    st.caption("Add an Anthropic API key to have Claude write a bull/bear thesis. "
               "Without it, everything else still works.")
    api_key = st.text_input("Anthropic API key", type="password",
                            help="Stored only in this session, never saved to disk.")
    model = st.selectbox("Model", [DEFAULT_MODEL, "claude-opus-4-8",
                                   "claude-haiku-4-5-20251001"], index=0)

st.title("📈 Stock Research Bot")
st.caption("Live news, earnings, price, and a transparent long/short lean. "
           "Research synthesis, **not** investment advice.")

# Navigation. key='view' ties the choice to session_state so code can change it.
st.segmented_control("Go to", VIEWS, key="view", label_visibility="collapsed")
view = st.session_state.get("view") or VIEWS[0]

# ===========================================================================
# VIEW 1: single-stock research
# ===========================================================================
if view == VIEWS[0]:
    ticker = st.text_input("Ticker", key="ticker", max_chars=8).strip().upper()

    if ticker:
        try:
            with st.spinner(f"Researching {ticker}…"):
                snap, bias, val, overall, fetched_at = load(ticker)
        except Exception as e:
            st.error(f"Couldn't load '{ticker}'. Is it a valid ticker? ({e})")
            st.stop()

        # yfinance returns EMPTY data (not an error) for a bad symbol, which would
        # render a hollow "Fairly Valued / HOLD" verdict. Catch that explicitly.
        if not (snap.get("price") or snap.get("current_price")):
            st.warning(f"Couldn't find market data for **{ticker}**. Double-check the "
                       "symbol — use the ticker, not the company name "
                       "(e.g. `TSLA` not `TESLA`, `GOOGL` not `GOOGLE`).")
            st.stop()

        def esc(text):                       # escape `$` so Streamlit doesn't read LaTeX
            return text.replace("$", "\\$")

        st.subheader(f"{snap['name']} ({snap['ticker']})")
        if snap["sector"]:
            st.caption(f"{snap['sector']} · {snap.get('industry') or ''}")

        # ---- THE HEADLINE VERDICT: stance + valuation + confidence ----
        s_color = STANCE_COLORS.get(overall["stance"], "#9ca3af")
        v_color = VERDICT_COLORS.get(val["verdict"], "#9ca3af")
        c_color = CONF_COLORS.get(overall["confidence"], "#9ca3af")
        st.markdown(
            f"<div style='display:flex;gap:10px;align-items:center;flex-wrap:wrap;'>"
            f"<span style='padding:6px 16px;border-radius:8px;background:{s_color};"
            f"color:white;font-size:20px;font-weight:700;'>{overall['stance']}</span>"
            f"<span style='padding:6px 14px;border-radius:8px;background:{v_color};"
            f"color:white;font-size:16px;font-weight:600;'>{val['verdict']}</span>"
            f"<span style='padding:6px 12px;border-radius:8px;border:1px solid {c_color};"
            f"color:{c_color};font-size:14px;font-weight:600;'>confidence: {overall['confidence']}</span>"
            f"</div>"
            f"<div style='margin-top:6px;color:#aaa;'>{esc(overall['summary'])} · "
            f"data as of {fetched_at}</div>",
            unsafe_allow_html=True,
        )
        st.caption("⚠️ Not financial advice — a structured synthesis of public data. "
                   "The market already knows all of this; treat it as a second opinion.")

        # ---- THE BOTTOM LINE: a plain-English summary of the whole verdict ----
        st.markdown(f"> {esc(why_summary(snap, bias, val, overall))}")

        # ---- key numbers (now valuation-led) ----
        up = val["upside"]
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Price", f"${num(snap['price'])}")
        c2.metric("Analyst target", f"${num(val['fair_value'])}" if val["fair_value"] else "--")
        c3.metric("Implied upside", f"{up:+.0%}" if up is not None else "--")
        c4.metric("P/E (fwd)", f"{num(snap['pe'])} ({num(snap['forward_pe'])})")
        c5.metric("ROE", pct(snap["roe"]))
        c6.metric("12-mo", pct(snap["mom_12m"]))

        hist = snap["hist"]
        if hist is not None and not hist.empty:
            chart = pd.DataFrame({
                "Price": hist["Close"],
                "50-day avg": hist["Close"].rolling(50).mean(),
                "200-day avg": hist["Close"].rolling(200).mean(),
            })
            # show the analyst target as a reference line on the chart
            if val["fair_value"]:
                chart["Analyst target"] = val["fair_value"]
            st.line_chart(chart, height=320)

        # ---- VALUATION: why it's cheap or rich ----
        st.markdown(f"### 💰 Valuation — **{val['verdict']}**")
        if val["fair_value"] and snap.get("target_low") and snap.get("target_high"):
            st.caption(f"Analyst fair-value range: \\${num(snap['target_low'])} (low) · "
                       f"\\${num(val['fair_value'])} (mean) · \\${num(snap['target_high'])} (high) "
                       f"across {snap.get('n_analysts') or '?'} analysts.")
        vleft, vright = st.columns(2)
        with vleft:
            st.markdown("**🟢 Looks cheap because**")
            for r in val["cheap"]:
                st.markdown(f"- {esc(r)}")
            if not val["cheap"]:
                st.markdown("_No cheap signals._")
        with vright:
            st.markdown("**🔴 Looks rich because**")
            for r in val["rich"]:
                st.markdown(f"- {esc(r)}")
            if not val["rich"]:
                st.markdown("_No rich signals._")

        # ---- analyst rating breakdown ----
        rt = snap.get("rec_trend")
        if rt and rt.get("total"):
            c = rt["counts"]
            st.caption(
                f"**Analyst ratings:** {c['strongBuy']} strong-buy · {c['buy']} buy · "
                f"{c['hold']} hold · {c['sell']} sell · {c['strongSell']} strong-sell "
                f"({rt['bullish_pct']:.0%} bullish)")

        # ---- KEY RATIOS (one consolidated reference grid) ----
        st.markdown("### 📐 Key ratios")
        fcf_yield = (snap["fcf"] / snap["market_cap"]) if (snap.get("fcf") and snap.get("market_cap")) else None
        dy = snap.get("div_yield")
        dy_str = f"{dy:.2f}%" if isinstance(dy, (int, float)) else "--"   # already in %
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            st.markdown(
                "**Valuation**\n"
                f"- P/E trailing: {num(snap['pe'])}\n"
                f"- P/E forward: {num(snap['forward_pe'])}\n"
                f"- PEG: {num(snap['peg'])}\n"
                f"- P/B: {num(snap['pb'])}\n"
                f"- P/S: {num(snap['ps'])}\n"
                f"- EV/EBITDA: {num(snap['ev_ebitda'])}\n"
                f"- FCF yield: {pct(fcf_yield)}\n"
                f"- Dividend yield: {dy_str}")
        with rc2:
            st.markdown(
                "**Quality**\n"
                f"- ROE: {pct(snap['roe'])}\n"
                f"- Gross margin: {pct(snap['gross_margin'])}\n"
                f"- Net margin: {pct(snap['margin'])}\n"
                f"- Debt/Equity: {num(snap['de'])}")
        with rc3:
            st.markdown(
                "**Growth**\n"
                f"- Revenue growth: {pct(snap['rev_growth'])}\n"
                f"- Earnings growth: {pct(snap['earn_growth'])}")

        # ---- FINANCIALS (revenue & net-income trend) ----
        fin = snap.get("financials")
        if fin and fin.get("years"):
            st.markdown("### 📑 Financials (annual)")
            yrs = fin["years"]
            order = list(reversed(range(len(yrs))))        # oldest -> newest (L→R)

            def billions(key, i):
                v = fin[key][i]
                return round(v / 1e9, 1) if isinstance(v, (int, float)) else None

            fdf = pd.DataFrame(
                {"Revenue ($B)": [billions("revenue", i) for i in order],
                 "Net income ($B)": [billions("net_income", i) for i in order]},
                index=[yrs[i] for i in order])
            st.bar_chart(fdf, height=260)

            margins = []
            for i in order:
                rev, ni = fin["revenue"][i], fin["net_income"][i]
                margins.append(f"{ni / rev * 100:.1f}%" if (rev and ni) else "--")
            tbl = pd.DataFrame({
                "Year": [yrs[i] for i in order],
                "Revenue ($B)": [billions("revenue", i) for i in order],
                "Net income ($B)": [billions("net_income", i) for i in order],
                "Net margin": margins,
            })
            st.dataframe(tbl, hide_index=True, use_container_width=True)

        # ---- TREND & QUALITY signals (the old momentum/quality scorecard) ----
        st.markdown("### 📊 Trend & quality signals")
        left, right = st.columns(2)
        with left:
            st.markdown("**🟢 Supporting**")
            for r in bias["bull"]:
                st.markdown(f"- {esc(r)}")
            if not bias["bull"]:
                st.markdown("_None fired._")
        with right:
            st.markdown("**🔴 Against**")
            for r in bias["bear"]:
                st.markdown(f"- {esc(r)}")
            if not bias["bear"]:
                st.markdown("_None fired._")

        # ---- earnings beat/miss track record ----
        eh = snap.get("earnings_history")
        if eh:
            st.markdown("### 📈 Earnings track record")
            beats = sum(1 for e in eh if (e.get("surprise") or 0) > 0)
            st.caption(f"Beat estimates in {beats} of the last {len(eh)} reported quarters.")
            edf = pd.DataFrame([{
                "Quarter": e["date"],
                "EPS est.": e["estimate"],
                "Reported": e["reported"],
                "Surprise %": e["surprise"],
            } for e in eh])
            st.dataframe(edf, hide_index=True, use_container_width=True,
                         column_config={"Surprise %": st.column_config.NumberColumn(format="%.1f%%")})

        st.markdown("### 📰 Recent news")
        if snap["news"]:
            for n in snap["news"]:
                news_item(n)
        else:
            st.caption("No recent news returned.")

        st.markdown("### 🤖 AI analyst thesis")
        if not api_key:
            st.caption("Add an Anthropic API key in the sidebar to generate a written "
                       "bull/bear thesis grounded in the scorecard above.")
        elif st.button(f"Generate thesis for {snap['ticker']}", type="primary"):
            try:
                with st.spinner("Claude is writing the note…"):
                    thesis = write_thesis(snap, bias, api_key=api_key, model=model)
                st.markdown(thesis)
            except Exception as e:
                st.error(f"AI thesis failed: {e}")

        if snap["next_earnings"]:
            st.info(f"🗓️ Next earnings (estimated): **{snap['next_earnings']}**")
        if snap.get("summary"):
            with st.expander("Business summary"):
                st.write(snap["summary"])

# ===========================================================================
# VIEW 2: Watchlist -- your stocks, each with a buy/hold/avoid verdict
# ===========================================================================
elif view == VIEWS[1]:
    st.markdown("### 📋 Watchlist — buy / watch / avoid")
    st.caption("Your stocks, each run through the full valuation + trend engine. "
               "**Use the dropdown below (or click a row's checkbox)** to open one in "
               "Stock Research. Not financial advice.")

    wl = load_watchlist()
    with st.expander("✏️ Edit your watchlist"):
        text = st.text_area("Tickers (comma or space separated)",
                            value=", ".join(wl), key="wl_text", height=80)
        if st.button("💾 Save & run", type="primary"):
            save_watchlist(parse_tickers(text))
            load_board.clear()
            st.rerun()

    tickers = parse_tickers(st.session_state.get("wl_text") or ", ".join(wl))
    board = []
    try:
        with st.spinner(f"Scoring {len(tickers)} stocks…"):
            board, board_at = load_board(tuple(tickers))
    except Exception as e:
        st.error(f"Couldn't build the board: {e}")

    if board:
        df = pd.DataFrame(board)
        st.caption(f"{len(df)} stocks scored · data as of {board_at}")
        open_picker(df["Ticker"].tolist(), "wl_open")     # reliable way to open a stock
        cfg = {
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Upside %": st.column_config.NumberColumn(format="%+.1f%%"),
        }
        cols = ["Ticker", "Name", "Price", "Stance", "Valuation",
                "Upside %", "Trend", "Confidence"]

        buys = df[df["Stance"] == "BUY LEAN"].sort_values("_score", ascending=False)
        watch = df[(df["Stance"] == "HOLD / NEUTRAL") &
                   ((df["Valuation"] == "Undervalued") | (df["Upside %"] > 10))
                   ].sort_values("Upside %", ascending=False)
        avoid = df[df["Stance"] == "AVOID LEAN"].sort_values("_score")
        shown = set(buys["Ticker"]) | set(watch["Ticker"]) | set(avoid["Ticker"])
        rest = df[~df["Ticker"].isin(shown)].sort_values("_score", ascending=False)

        picked = None
        st.markdown(f"#### 🟢 Buy leans ({len(buys)})")
        st.caption("Cheap-enough **and** the trend is working — the strongest setups.")
        picked = selectable_table(buys[cols], "wl_buy", cfg, "Ticker") or picked

        st.markdown(f"#### 👀 Watch closely ({len(watch)})")
        st.caption("Undervalued / has upside, but the trend hasn't confirmed yet — "
                   "keep an eye on these to buy.")
        picked = selectable_table(watch[cols], "wl_watch", cfg, "Ticker") or picked

        st.markdown(f"#### ⚪ The rest ({len(rest)})")
        picked = selectable_table(rest[cols], "wl_rest", cfg, "Ticker") or picked

        st.markdown(f"#### 🔴 Avoid ({len(avoid)})")
        st.caption("Overvalued and/or the trend is against you.")
        picked = selectable_table(avoid[cols], "wl_avoid", cfg, "Ticker") or picked

        if picked:
            go_to_research(picked)

# ===========================================================================
# VIEW 3: Radar -- catalyst-driven idea discovery (rows are clickable!)
# ===========================================================================
elif view == VIEWS[2]:
    st.markdown("### 📡 What's worth a look right now")
    st.caption("Stocks with a **catalyst** — a reason they're in play today. "
               "**Use the dropdown below (or click a row's checkbox)** to open one in "
               "Stock Research. A catalyst is a reason to *research*, not a reason to buy.")

    try:
        with st.spinner("Scanning the market…"):
            radar = load_radar()
    except Exception as e:
        st.error(f"Couldn't load radar feeds: {e}")
        radar = None

    if radar:
        st.caption(f"Data as of {radar['at']}")

        # collect every ticker shown on the radar for the dropdown picker
        radar_syms = []
        for k in ["earnings", "surprises", "gainers", "losers", "actives", "ipos"]:
            d = radar.get(k)
            if d is not None and not d.empty and "Symbol" in d:
                radar_syms += d["Symbol"].dropna().tolist()
        open_picker(radar_syms, "radar_open")

        picked = None      # first ticker clicked anywhere wins

        # --- earnings ---
        st.markdown("#### 📅 Reporting earnings in the next 7 days")
        st.caption("Timing: BMO = before market open · AMC = after market close.")
        ev = radar["earnings"]
        if ev is not None and not ev.empty:
            ev = ev.copy()
            if "Marketcap" in ev:
                ev["Marketcap"] = (ev["Marketcap"] / 1e9).round(2)
            picked = selectable_table(ev, "earn", {
                "Marketcap": st.column_config.NumberColumn("Mkt Cap ($B)", format="%.1f")
            }) or picked
        else:
            st.caption("No upcoming earnings returned.")

        # --- recent surprises ---
        st.markdown("#### 🎯 Just reported — beats & misses")
        st.caption("Surprise(%) = how far reported EPS beat (+) or missed (–) estimates.")
        picked = selectable_table(radar["surprises"], "surp", {
            "Surprise(%)": st.column_config.NumberColumn(format="%.1f%%")
        }) or picked

        # --- movers ---
        st.markdown("#### 🔥 Today's movers")
        mov_cfg = {
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "% Change": st.column_config.NumberColumn(format="%.2f%%"),
            "Mkt Cap": st.column_config.NumberColumn("Mkt Cap ($B)", format="%.1f"),
        }

        def prep_movers(df):
            if df is None or df.empty:
                return df
            d = df.copy()
            if "Mkt Cap" in d:
                d["Mkt Cap"] = (d["Mkt Cap"] / 1e9).round(2)
            return d

        mleft, mright = st.columns(2)
        with mleft:
            st.markdown("**🟢 Top gainers**")
            picked = selectable_table(prep_movers(radar["gainers"]), "gain", mov_cfg) or picked
        with mright:
            st.markdown("**🔴 Top losers**")
            picked = selectable_table(prep_movers(radar["losers"]), "lose", mov_cfg) or picked
        st.markdown("**🔁 Most active**")
        picked = selectable_table(prep_movers(radar["actives"]), "act", mov_cfg) or picked

        # --- IPOs ---
        st.markdown("#### 🆕 IPOs (recent & upcoming)")
        st.caption("Brand-new listings. Fund/ETF launches are filtered out.")
        picked = selectable_table(radar["ipos"], "ipo") or picked

        # If anything was clicked, jump to research with that ticker.
        if picked:
            go_to_research(picked)

# ===========================================================================
# VIEW 4: general business / market news
# ===========================================================================
elif view == VIEWS[3]:
    st.markdown("### 🌎 Today's business & market headlines")
    try:
        with st.spinner("Pulling market news…"):
            market_news, news_fetched = load_market_news()
        st.caption(f"Aggregated & de-duplicated across SPY, QQQ, DIA, S&P 500, "
                   f"Nasdaq · data as of {news_fetched}")
        if market_news:
            for n in market_news:
                news_item(n)
                st.markdown("")
        else:
            st.caption("No market news returned right now — try Refresh.")
    except Exception as e:
        st.error(f"Couldn't load market news: {e}")

# ===========================================================================
# VIEW 5: Track Record -- is the bot actually right?
# ===========================================================================
elif view == VIEWS[4]:
    st.markdown("### 📈 Track record — is the bot actually right?")
    st.caption("Log today's verdicts, then come back over weeks and months to see "
               "whether **BUY leans actually beat AVOIDs** — measured against the "
               "S&P 500 (SPY), because beating the market is the only bar that counts. "
               "This is the only honest way to know if any of this works.")

    if st.button("📌 Log today's watchlist verdicts", type="primary"):
        wl = load_watchlist()
        with st.spinner("Scoring & logging today's verdicts…"):
            rows, _ = load_board(tuple(wl))
            n = log_verdicts(rows)
        score_tracker.clear()
        st.success(f"Logged {n} verdicts for today. Come back later to see how they age.")

    try:
        scored = score_tracker()
    except Exception as e:
        scored = None
        st.error(f"Couldn't score the log: {e}")

    if not scored:
        st.info("No verdicts logged yet. Click **Log today's watchlist verdicts** to "
                "start your track record — then check back in a few weeks. The whole "
                "point is that it takes time to mean anything.")
    else:
        st.markdown(f"#### Scorecard — {scored['n']} verdicts, up to {scored['days_span']} days old")
        if scored["days_span"] < 14:
            st.warning("⏳ This is far too fresh to mean anything — returns over a few "
                       "days are pure noise. Keep logging; judge it in months, not days.")

        summ = scored["summary"]
        if summ is not None and not summ.empty:
            st.dataframe(summ, hide_index=True, use_container_width=True, column_config={
                "n": st.column_config.NumberColumn("# verdicts"),
                "avg_return": st.column_config.NumberColumn("Avg return", format="%.1f%%"),
                "avg_vs_spy": st.column_config.NumberColumn("Avg vs SPY", format="%+.1f%%"),
                "beat_spy": st.column_config.NumberColumn("Beat SPY", format="%.0f%%"),
            })

            # the headline honest question: do BUY leans beat AVOID leans vs SPY?
            by = summ.set_index("stance")["avg_vs_spy"].to_dict()
            buy, avoid = by.get("BUY LEAN"), by.get("AVOID LEAN")
            if buy is not None and avoid is not None:
                spread = buy - avoid
                msg = (f"So far, **BUY leans are beating AVOID leans by {spread:+.1f}%** "
                       "vs the S&P 500." if spread > 0 else
                       f"So far, there's **no edge** — BUY leans trail AVOIDs by "
                       f"{spread:.1f}% vs SPY. That's a valuable answer too.")
                (st.success if spread > 0 else st.warning)(
                    msg + "  _(Tiny sample — don't read much into it yet.)_")

        st.markdown("#### Every logged verdict, graded")
        st.dataframe(
            scored["detail"].sort_values("date"), hide_index=True,
            use_container_width=True, column_config={
                "logged_price": st.column_config.NumberColumn(format="$%.2f"),
                "current_price": st.column_config.NumberColumn(format="$%.2f"),
                "return_%": st.column_config.NumberColumn("Return", format="%+.1f%%"),
                "vs_SPY_%": st.column_config.NumberColumn("vs SPY", format="%+.1f%%"),
            })

# ---- shared footer ---------------------------------------------------------
st.divider()
st.caption(
    "⚠️ This is a transparent rule-based synthesis of public data for research "
    "and learning. It is not investment advice and not a money signal — markets "
    "are roughly efficient and these factors are widely known. Always do your own work."
)
