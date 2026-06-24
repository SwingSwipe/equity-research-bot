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
from catalysts import (get_movers, get_upcoming_earnings,
                       get_recent_surprises, get_ipos)
from llm import write_thesis, DEFAULT_MODEL

st.set_page_config(page_title="Stock Research Bot", page_icon="📈", layout="wide")

VIEWS = ["🔍 Stock Research", "📡 Radar", "🌎 Market News"]


# ---------------------------------------------------------------------------
# DATA LOADERS (cached). Quotes are ~15 min delayed on free Yahoo data; the
# cache re-pulls every 5 min, and the sidebar Refresh button forces it.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load(ticker: str):
    snap = get_snapshot(ticker)
    bias = compute_bias(snap)
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return snap, bias, fetched_at


@st.cache_data(ttl=300, show_spinner=False)
def load_market_news():
    return get_market_news(limit=25), datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def selectable_table(df, base_key, column_config=None):
    """Show a dataframe whose rows are clickable; return the clicked ticker."""
    if df is None or df.empty:
        st.caption("None returned right now.")
        return None
    key = f"{base_key}_{st.session_state.nav_token}"     # fresh key after a jump
    event = st.dataframe(
        df, key=key, on_select="rerun", selection_mode="single-row",
        hide_index=True, use_container_width=True, column_config=column_config or {},
    )
    rows = event.selection.rows
    return str(df.iloc[rows[0]]["Symbol"]) if rows else None


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
                snap, bias, fetched_at = load(ticker)
        except Exception as e:
            st.error(f"Couldn't load '{ticker}'. Is it a valid ticker? ({e})")
            st.stop()

        st.subheader(f"{snap['name']} ({snap['ticker']})")
        if snap["sector"]:
            st.caption(f"{snap['sector']} · {snap.get('industry') or ''}")

        color = LEAN_COLORS.get(bias["lean"], "#9ca3af")
        st.markdown(
            f"<div style='display:inline-block;padding:6px 16px;border-radius:8px;"
            f"background:{color};color:white;font-size:20px;font-weight:700;'>"
            f"LEAN: {bias['lean']}</div>"
            f"<span style='margin-left:12px;color:#888;'>"
            f"bull {bias['bull_score']} vs bear {bias['bear_score']} · "
            f"data as of {fetched_at}</span>",
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Price", f"${num(snap['price'])}")
        c2.metric("12-mo return", pct(snap["mom_12m"]))
        c3.metric("P/E", num(snap["pe"]))
        c4.metric("ROE", pct(snap["roe"]))
        c5.metric("Market cap", num(snap["market_cap"], dollars=True))

        hist = snap["hist"]
        if hist is not None and not hist.empty:
            chart = pd.DataFrame({
                "Price": hist["Close"],
                "50-day avg": hist["Close"].rolling(50).mean(),
                "200-day avg": hist["Close"].rolling(200).mean(),
            })
            st.line_chart(chart, height=320)

        def esc(text):                       # escape `$` so Streamlit doesn't read LaTeX
            return text.replace("$", "\\$")

        left, right = st.columns(2)
        with left:
            st.markdown("### 🟢 Bull case")
            for r in bias["bull"]:
                st.markdown(f"- {esc(r)}")
            if not bias["bull"]:
                st.markdown("_No bullish signals fired._")
        with right:
            st.markdown("### 🔴 Bear case")
            for r in bias["bear"]:
                st.markdown(f"- {esc(r)}")
            if not bias["bear"]:
                st.markdown("_No bearish signals fired._")

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
# VIEW 2: Radar -- catalyst-driven idea discovery (rows are clickable!)
# ===========================================================================
elif view == VIEWS[1]:
    st.markdown("### 📡 What's worth a look right now")
    st.caption("Stocks with a **catalyst** — a reason they're in play today. "
               "**Click any row** to load that ticker in Stock Research. "
               "A catalyst is a reason to *research*, not a reason to buy.")

    try:
        with st.spinner("Scanning the market…"):
            radar = load_radar()
    except Exception as e:
        st.error(f"Couldn't load radar feeds: {e}")
        radar = None

    if radar:
        st.caption(f"Data as of {radar['at']}")
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
# VIEW 3: general business / market news
# ===========================================================================
elif view == VIEWS[2]:
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

# ---- shared footer ---------------------------------------------------------
st.divider()
st.caption(
    "⚠️ This is a transparent rule-based synthesis of public data for research "
    "and learning. It is not investment advice and not a money signal — markets "
    "are roughly efficient and these factors are widely known. Always do your own work."
)
