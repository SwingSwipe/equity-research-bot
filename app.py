"""
app.py  --  the web UI for the single-stock research bot.

Run it with:   python -m streamlit run app.py
Then your browser opens; type a ticker (e.g. AAPL) and hit Enter.

This file is ONLY presentation. All the thinking lives in analyst.py.
Streamlit re-runs this whole script top-to-bottom on every interaction --
that's its model: your script *is* the page.
"""

import pandas as pd
import streamlit as st

from analyst import get_snapshot, compute_bias, num, pct
from llm import write_thesis, DEFAULT_MODEL

st.set_page_config(page_title="Stock Research Bot", page_icon="📈", layout="wide")

# ---- sidebar: optional Anthropic API key for the AI analyst ----------------
with st.sidebar:
    st.markdown("### 🤖 AI Analyst (optional)")
    st.caption("Add an Anthropic API key to have Claude write a bull/bear thesis. "
               "Without it, everything else still works.")
    api_key = st.text_input("Anthropic API key", type="password",
                            help="Stored only in this session, never saved to disk.")
    model = st.selectbox("Model", [DEFAULT_MODEL, "claude-opus-4-8",
                                   "claude-haiku-4-5-20251001"], index=0)

# Cache so typing the same ticker twice doesn't re-hit the network.
# ttl=900 -> data is considered fresh for 15 minutes.
@st.cache_data(ttl=900, show_spinner=False)
def load(ticker: str):
    snap = get_snapshot(ticker)
    bias = compute_bias(snap)
    return snap, bias


# colors for the headline lean badge
LEAN_COLORS = {
    "LONG": "#16a34a", "LEAN LONG": "#4ade80", "NEUTRAL": "#9ca3af",
    "LEAN SHORT": "#f87171", "SHORT": "#dc2626",
}

st.title("📈 Stock Research Bot")
st.caption("Type a ticker → news, earnings, price, and a transparent long/short lean. "
           "Research synthesis, **not** investment advice.")

ticker = st.text_input("Ticker", value="AAPL", max_chars=8).strip().upper()

if ticker:
    try:
        with st.spinner(f"Researching {ticker}…"):
            snap, bias = load(ticker)
    except Exception as e:
        st.error(f"Couldn't load '{ticker}'. Is it a valid ticker? ({e})")
        st.stop()

    # ---- header: name + the headline lean badge ----------------------------
    st.subheader(f"{snap['name']} ({snap['ticker']})")
    if snap["sector"]:
        st.caption(f"{snap['sector']} · {snap.get('industry') or ''}")

    color = LEAN_COLORS.get(bias["lean"], "#9ca3af")
    st.markdown(
        f"<div style='display:inline-block;padding:6px 16px;border-radius:8px;"
        f"background:{color};color:white;font-size:20px;font-weight:700;'>"
        f"LEAN: {bias['lean']}</div>"
        f"<span style='margin-left:12px;color:#888;'>"
        f"bull {bias['bull_score']} vs bear {bias['bear_score']}</span>",
        unsafe_allow_html=True,
    )

    # ---- key numbers across the top -----------------------------------------
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Price", f"${num(snap['price'])}")
    c2.metric("12-mo return", pct(snap["mom_12m"]))
    c3.metric("P/E", num(snap["pe"]))
    c4.metric("ROE", pct(snap["roe"]))
    c5.metric("Market cap", num(snap["market_cap"], dollars=True))

    # ---- price chart with 50 & 200-day moving averages ----------------------
    hist = snap["hist"]
    if hist is not None and not hist.empty:
        chart = pd.DataFrame({
            "Price": hist["Close"],
            "50-day avg": hist["Close"].rolling(50).mean(),
            "200-day avg": hist["Close"].rolling(200).mean(),
        })
        st.line_chart(chart, height=320)

    # ---- the bull / bear case, side by side ---------------------------------
    left, right = st.columns(2)
    # NOTE: Streamlit markdown treats `$` as the start of a LaTeX math block,
    # so we escape every `$` to `\$` before displaying our reason strings.
    def esc(text):
        return text.replace("$", "\\$")

    with left:
        st.markdown("### 🟢 Bull case")
        if bias["bull"]:
            for r in bias["bull"]:
                st.markdown(f"- {esc(r)}")
        else:
            st.markdown("_No bullish signals fired._")
    with right:
        st.markdown("### 🔴 Bear case")
        if bias["bear"]:
            for r in bias["bear"]:
                st.markdown(f"- {esc(r)}")
        else:
            st.markdown("_No bearish signals fired._")

    # ---- recent news --------------------------------------------------------
    st.markdown("### 📰 Recent news")
    if snap["news"]:
        for n in snap["news"]:
            title = n["title"] or "(untitled)"
            meta = " · ".join(x for x in [n.get("publisher"), (n.get("date") or "")[:10]] if x)
            if n.get("url"):
                st.markdown(f"**[{title}]({n['url']})**  \n<span style='color:#888'>{meta}</span>",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"**{title}**  \n<span style='color:#888'>{meta}</span>",
                            unsafe_allow_html=True)
            if n.get("summary"):
                st.caption(n["summary"])
    else:
        st.caption("No recent news returned.")

    # ---- AI analyst thesis (on demand, only if a key is provided) -----------
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

    # ---- footer: earnings + business summary --------------------------------
    if snap["next_earnings"]:
        st.info(f"🗓️ Next earnings (estimated): **{snap['next_earnings']}**")
    if snap.get("summary"):
        with st.expander("Business summary"):
            st.write(snap["summary"])

    st.divider()
    st.caption(
        "⚠️ This is a transparent rule-based synthesis of public data for research "
        "and learning. It is not investment advice and not a money signal — markets "
        "are roughly efficient and these factors are widely known. Always do your own work."
    )
