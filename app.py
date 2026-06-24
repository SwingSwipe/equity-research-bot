"""
app.py  --  the web UI for the stock research bot.

Run it with:   python -m streamlit run app.py
Then your browser opens; type a ticker (e.g. AAPL) and hit Enter.

This file is ONLY presentation. All the thinking lives in analyst.py.
Streamlit re-runs this whole script top-to-bottom on every interaction --
that's its model: your script *is* the page.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from analyst import get_snapshot, compute_bias, get_market_news, num, pct
from catalysts import (get_movers, get_upcoming_earnings,
                       get_recent_surprises, get_ipos)
from llm import write_thesis, DEFAULT_MODEL

st.set_page_config(page_title="Stock Research Bot", page_icon="📈", layout="wide")

# ---------------------------------------------------------------------------
# DATA LOADERS (cached). On free Yahoo data, quotes are delayed ~15 min and
# refreshed live every time the cache expires. ttl=300 -> re-pull after 5 min;
# the sidebar Refresh button force-clears it for an instant re-pull.
# The fetched-at timestamp is captured *inside* the cached call, so it honestly
# reflects when the data was actually pulled, not when the page re-rendered.
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
    """All the catalyst feeds for the Radar tab, in one cached pull."""
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
    """Render one news story (used by both tabs)."""
    title = n["title"] or "(untitled)"
    meta = " · ".join(x for x in [n.get("publisher"), (n.get("date") or "")[:10]] if x)
    link = f"[{title}]({n['url']})" if n.get("url") else f"**{title}**"
    st.markdown(f"**{link}**  \n<span style='color:#888'>{meta}</span>",
                unsafe_allow_html=True)
    if n.get("summary"):
        st.caption(n["summary"])


# ---- sidebar: refresh + optional Anthropic API key -------------------------
with st.sidebar:
    if st.button("🔄 Refresh data", use_container_width=True):
        load.clear()                 # drop cached single-stock pulls
        load_market_news.clear()     # drop cached market news
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

tab_research, tab_radar, tab_market = st.tabs(
    ["🔍 Stock Research", "📡 Radar", "🌎 Market News"])

# ===========================================================================
# TAB 1: single-stock research
# ===========================================================================
with tab_research:
    ticker = st.text_input("Ticker", value="AAPL", max_chars=8).strip().upper()

    if ticker:
        try:
            with st.spinner(f"Researching {ticker}…"):
                snap, bias, fetched_at = load(ticker)
        except Exception as e:
            st.error(f"Couldn't load '{ticker}'. Is it a valid ticker? ({e})")
            st.stop()

        # header: name + lean badge + data-as-of stamp
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

        # key numbers
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Price", f"${num(snap['price'])}")
        c2.metric("12-mo return", pct(snap["mom_12m"]))
        c3.metric("P/E", num(snap["pe"]))
        c4.metric("ROE", pct(snap["roe"]))
        c5.metric("Market cap", num(snap["market_cap"], dollars=True))

        # price chart with moving averages
        hist = snap["hist"]
        if hist is not None and not hist.empty:
            chart = pd.DataFrame({
                "Price": hist["Close"],
                "50-day avg": hist["Close"].rolling(50).mean(),
                "200-day avg": hist["Close"].rolling(200).mean(),
            })
            st.line_chart(chart, height=320)

        # bull / bear case
        # NOTE: Streamlit markdown treats `$` as the start of a LaTeX math block,
        # so we escape every `$` to `\$` before displaying our reason strings.
        def esc(text):
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

        # recent news for this stock
        st.markdown("### 📰 Recent news")
        if snap["news"]:
            for n in snap["news"]:
                news_item(n)
        else:
            st.caption("No recent news returned.")

        # AI analyst thesis (on demand, only if a key is provided)
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

        # footer extras
        if snap["next_earnings"]:
            st.info(f"🗓️ Next earnings (estimated): **{snap['next_earnings']}**")
        if snap.get("summary"):
            with st.expander("Business summary"):
                st.write(snap["summary"])

# ===========================================================================
# TAB 2: Radar -- catalyst-driven idea discovery
# ===========================================================================
def show_movers(df, label):
    """Render a movers table with market cap in $B and tidy columns."""
    st.markdown(f"**{label}**")
    if df is None or df.empty:
        st.caption("None returned right now.")
        return
    d = df.copy()
    if "Mkt Cap" in d:
        d["Mkt Cap"] = (d["Mkt Cap"] / 1e9).round(2)   # -> billions
    st.dataframe(
        d, hide_index=True, use_container_width=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "% Change": st.column_config.NumberColumn(format="%.2f%%"),
            "Mkt Cap": st.column_config.NumberColumn("Mkt Cap ($B)", format="%.1f"),
        },
    )


with tab_radar:
    st.markdown("### 📡 What's worth a look right now")
    st.caption("Stocks with a **catalyst** — a reason they're in play today. "
               "A catalyst is a reason to *research*, not a reason to buy. "
               "Spot something interesting? Type its ticker into the 🔍 Stock Research tab.")

    try:
        with st.spinner("Scanning the market…"):
            radar = load_radar()
    except Exception as e:
        st.error(f"Couldn't load radar feeds: {e}")
        radar = None

    if radar:
        st.caption(f"Data as of {radar['at']}")

        # --- earnings ---
        st.markdown("#### 📅 Reporting earnings in the next 7 days")
        st.caption("Timing: BMO = before market open · AMC = after market close. "
                   "Earnings = the biggest scheduled catalyst there is.")
        e = radar["earnings"]
        if e is not None and not e.empty:
            ev = e.copy()
            if "Marketcap" in ev:
                ev["Marketcap"] = (ev["Marketcap"] / 1e9).round(2)
            st.dataframe(ev, hide_index=True, use_container_width=True,
                         column_config={"Marketcap": st.column_config.NumberColumn(
                             "Mkt Cap ($B)", format="%.1f")})
        else:
            st.caption("No upcoming earnings returned.")

        # --- recent surprises ---
        st.markdown("#### 🎯 Just reported — beats & misses")
        st.caption("Surprise(%) = how far reported EPS beat (+) or missed (–) estimates.")
        s = radar["surprises"]
        if s is not None and not s.empty:
            st.dataframe(s, hide_index=True, use_container_width=True,
                         column_config={"Surprise(%)": st.column_config.NumberColumn(
                             format="%.1f%%")})
        else:
            st.caption("No recent reports returned.")

        # --- movers ---
        st.markdown("#### 🔥 Today's movers")
        mleft, mright = st.columns(2)
        with mleft:
            show_movers(radar["gainers"], "🟢 Top gainers")
        with mright:
            show_movers(radar["losers"], "🔴 Top losers")
        show_movers(radar["actives"], "🔁 Most active")

        # --- IPOs ---
        st.markdown("#### 🆕 IPOs (recent & upcoming)")
        st.caption("Brand-new listings. Fund/ETF launches are filtered out to show real companies.")
        ipo = radar["ipos"]
        if ipo is not None and not ipo.empty:
            st.dataframe(ipo, hide_index=True, use_container_width=True)
        else:
            st.caption("No company IPOs in the window right now.")


# ===========================================================================
# TAB 3: general business / market news
# ===========================================================================
with tab_market:
    st.markdown("### 🌎 Today's business & market headlines")
    try:
        with st.spinner("Pulling market news…"):
            market_news, news_fetched = load_market_news()
        st.caption(f"Aggregated & de-duplicated across SPY, QQQ, DIA, S&P 500, "
                   f"Nasdaq · data as of {news_fetched}")
        if market_news:
            for n in market_news:
                news_item(n)
                st.markdown("")  # a little breathing room between stories
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
