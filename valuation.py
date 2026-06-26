"""
valuation.py  --  the "is it undervalued or overvalued?" engine.

This is what turns raw data into a verdict. It looks at the stock through
several INDEPENDENT valuation lenses, each of which votes "cheap" or "rich"
with a plain-English reason:

  * Analyst price target   -- where Wall Street's consensus says it's worth
  * Analyst rating         -- buy / hold / sell consensus
  * PEG                    -- valuation adjusted for growth
  * Forward vs trailing P/E-- is it getting cheaper as earnings grow?
  * Free-cash-flow yield   -- cash returned per dollar of price
  * EV/EBITDA              -- enterprise value vs cash earnings

It then combines the votes into Undervalued / Fairly Valued / Overvalued, and --
crucially -- a CONFIDENCE level that drops when the lenses disagree or few
analysts cover the name. Honest uncertainty beats false precision.

HARD LIMITS (say them, don't bury them):
  * The market already knows all of this. A verdict is a structured second
    opinion, not an edge and not a price prediction.
  * EV/EBITDA and FCF-yield thresholds are rough and SECTOR-DEPENDENT -- a
    bank, a utility, and a software firm aren't 'cheap' at the same number.
  * Analyst targets are consensus, often lagging, and frequently wrong.
  * Not financial advice.
"""


# yfinance's sector name for banks/insurers/etc. -- where EV/EBITDA and FCF yield
# don't apply (banks have no meaningful EBITDA or free cash flow in the usual sense).
FINANCIAL_SECTORS = {"Financial Services"}


def _fcf_yield(snap):
    fcf, mcap = snap.get("fcf"), snap.get("market_cap")
    return (fcf / mcap) if (fcf and mcap) else None


def _num(x, dec=0):
    return f"{x:,.{dec}f}" if isinstance(x, (int, float)) else "--"


def value_verdict(snap: dict, benchmarks: dict = None) -> dict:
    """Return the valuation verdict dict for one stock's snapshot.

    If sector benchmarks are available, P/E and EV/EBITDA are judged RELATIVE to
    the stock's sector median (cheap/expensive *for its sector*) instead of by
    one-size-fits-all thresholds -- a big accuracy win across sectors."""
    if benchmarks is None:
        from benchmarks import load_benchmarks
        benchmarks = load_benchmarks()
    sec = snap.get("sector")
    secbm = benchmarks.get(sec, {}) if sec else {}
    is_financial = sec in FINANCIAL_SECTORS      # banks/insurers need special handling

    price = snap.get("price") or snap.get("current_price")

    # Each signal votes into a THEME as (reason, signed_strength). Correlated
    # signals share a theme, and each theme's total is CAPPED -- so four
    # different 'cheap on multiples' signals can't masquerade as +4 of
    # independent conviction when they're really one idea.
    votes = {"analyst": [], "multiples": [], "cash": []}
    CAPS = {"analyst": 3, "multiples": 2, "cash": 1}

    def add(theme, reason, signed):
        votes[theme].append((reason, signed))

    # --- ANALYST theme: price target + consensus rating ('what the Street thinks') ---
    tm = snap.get("target_mean")
    upside = (tm / price - 1) if (tm and price) else None
    if upside is not None:
        if upside > 0.15:
            add("analyst", f"Analyst mean target ${_num(tm)} is {upside:+.0%} above the "
                f"${_num(price,2)} price — Street sees upside.", 2)
        elif upside < -0.05:
            add("analyst", f"Price ${_num(price,2)} is above the ${_num(tm)} analyst "
                f"target ({upside:+.0%}) — Street sees downside.", -2)
    rm = snap.get("rec_mean")     # 1=strong buy ... 5=sell
    if isinstance(rm, (int, float)) and rm > 0:
        if rm <= 2.2:
            add("analyst", f"Consensus rating {rm:.1f}/5 ({snap.get('rec_key')}) across "
                f"{snap.get('n_analysts') or '?'} analysts — bullish.", 1)
        elif rm >= 3.0:
            add("analyst", f"Consensus rating {rm:.1f}/5 — analysts are cautious.", -1)

    # --- MULTIPLES theme: PEG, fwd-vs-trailing, P/E-vs-sector, EV/EBITDA
    #     (all the same underlying idea: 'cheap on fundamentals' -> capped) ---
    peg = snap.get("peg")
    if isinstance(peg, (int, float)) and peg > 0:
        if peg < 1.0:
            add("multiples", f"PEG {peg:.2f} (<1) — cheap relative to its growth.", 1)
        elif peg > 2.0:
            add("multiples", f"PEG {peg:.2f} (>2) — expensive relative to its growth.", -1)
    fpe, tpe = snap.get("forward_pe"), snap.get("pe")
    if all(isinstance(x, (int, float)) and x > 0 for x in [fpe, tpe]):
        if fpe < tpe * 0.9:
            add("multiples", f"Forward P/E {fpe:.1f} below trailing {tpe:.1f} — earnings "
                "expected to grow into the valuation.", 1)
        elif fpe > tpe * 1.1:
            add("multiples", f"Forward P/E {fpe:.1f} above trailing {tpe:.1f} — earnings "
                "expected to shrink.", -1)
    pe, pe_med = snap.get("pe"), secbm.get("pe")
    if isinstance(pe, (int, float)) and pe > 0 and pe_med:
        ratio = pe / pe_med
        if ratio < 0.8:
            add("multiples", f"P/E {pe:.1f} is below the {sec} sector median of "
                f"{pe_med:.0f} — cheap for its sector.", 1)
        elif ratio > 1.3:
            add("multiples", f"P/E {pe:.1f} is above the {sec} sector median of "
                f"{pe_med:.0f} — expensive for its sector.", -1)
    ee, ee_med = snap.get("ev_ebitda"), secbm.get("ev_ebitda")
    if not is_financial and isinstance(ee, (int, float)) and ee > 0:
        if ee_med:
            ratio = ee / ee_med
            if ratio < 0.8:
                add("multiples", f"EV/EBITDA {ee:.1f} vs the {sec} median {ee_med:.0f} "
                    "— cheap on cash earnings for its sector.", 1)
            elif ratio > 1.3:
                add("multiples", f"EV/EBITDA {ee:.1f} vs the {sec} median {ee_med:.0f} "
                    "— rich for its sector.", -1)
        elif ee < 10:
            add("multiples", f"EV/EBITDA {ee:.1f} (<10) — inexpensive on cash earnings.", 1)
        elif ee > 20:
            add("multiples", f"EV/EBITDA {ee:.1f} (>20) — richly valued on cash earnings.", -1)

    # --- CASH theme: free-cash-flow yield (not meaningful for financials) ---
    fy = None if is_financial else _fcf_yield(snap)
    if fy is not None:
        if fy > 0.05:
            add("cash", f"Free-cash-flow yield {fy:.1%} — strong cash return for the price.", 1)
        elif 0 < fy < 0.02:
            add("cash", f"Free-cash-flow yield only {fy:.1%} — you pay a lot per dollar of cash.", -1)

    # --- combine: cap each theme, then sum (de-correlation happens here) ---
    score = 0.0
    theme_scores = {}
    for t, vlist in votes.items():
        raw = sum(s for _, s in vlist)
        capped = max(-CAPS[t], min(CAPS[t], raw))
        theme_scores[t] = capped
        score += capped

    cheap = [r for vlist in votes.values() for (r, s) in vlist if s > 0]
    rich = [r for vlist in votes.values() for (r, s) in vlist if s < 0]
    n_signals = len(cheap) + len(rich)

    # --- verdict ---
    if score >= 3:
        verdict = "Undervalued"
    elif score <= -3:
        verdict = "Overvalued"
    else:
        verdict = "Fairly Valued"

    # --- confidence: needs CONVICTION (a clear score), enough independent
    #     signals, AND real analyst coverage. A borderline score is never 'High'. ---
    n_analysts = snap.get("n_analysts") or 0
    if abs(score) >= 3 and n_signals >= 4 and n_analysts >= 12:
        confidence = "High"
    elif abs(score) >= 2 and n_signals >= 3:
        confidence = "Medium"
    else:
        confidence = "Low"

    # --- DATA-SANITY FLAGS: warn when an input is broken or misleading, so the
    #     verdict is never silently built on garbage. ---
    flags = []
    pb = snap.get("pb")
    if isinstance(pb, (int, float)) and pb < 0:
        flags.append("Negative book value — P/B is meaningless here (heavy buybacks "
                     "or negative equity).")
    if not (isinstance(snap.get("pe"), (int, float)) and snap["pe"] > 0):
        flags.append("No positive trailing earnings — P/E and PEG don't apply; the "
                     "read leans on forward estimates and analyst targets.")
    if is_financial:
        flags.append("Financial-sector company — EV/EBITDA and free-cash-flow yield "
                     "aren't meaningful for banks/insurers, so they're skipped; P/E "
                     "and analyst views carry the valuation (P/B matters more here).")
    roe = snap.get("roe")
    if isinstance(roe, (int, float)) and roe > 0.6:
        flags.append(f"ROE of {roe * 100:.0f}% is likely flattered by buybacks / low "
                     "equity — treat the quality read with caution.")
    de = snap.get("de")
    if isinstance(de, (int, float)) and de > 300:
        flags.append(f"Very high debt/equity ({de:.0f}) — may reflect buybacks or "
                     "sector norms rather than distress; interpret carefully.")
    if secbm.get("_n") and secbm["_n"] < 5:
        flags.append(f"Thin sector benchmark (~{secbm['_n']} peers sampled) — the "
                     "sector comparison is rough.")

    return {
        "verdict": verdict, "score": score, "confidence": confidence,
        "fair_value": tm, "upside": upside,
        "cheap": cheap, "rich": rich, "n_signals": n_signals, "themes": theme_scores,
        "sector": sec, "sector_pe": secbm.get("pe"), "sector_ev": secbm.get("ev_ebitda"),
        "flags": flags,
    }


def overall_verdict(snap: dict, bias: dict, val: dict) -> dict:
    """Merge the VALUATION verdict with the momentum/quality bias scorecard
    into one buy/hold/avoid stance. Valuation answers 'is it cheap?'; the bias
    answers 'is it working?'. You want both pointing the same way."""
    combined = val["score"] + bias["net"]

    # Gate first on valuation so we never call an overvalued name a "buy" just
    # because momentum is hot (that's how you buy the top), or an undervalued
    # name an "avoid" purely on a dip.
    if val["verdict"] == "Overvalued":
        stance = "AVOID LEAN" if bias["net"] <= 0 else "HOLD / NEUTRAL"
    elif val["verdict"] == "Undervalued":
        stance = "BUY LEAN" if bias["net"] >= 0 else "HOLD / NEUTRAL"
    elif combined >= 4:
        stance = "BUY LEAN"
    elif combined <= -4:
        stance = "AVOID LEAN"
    else:
        stance = "HOLD / NEUTRAL"

    # one-line summary tying valuation + trend together
    trend_word = ("improving" if bias["net"] > 0 else
                  "deteriorating" if bias["net"] < 0 else "mixed")
    summary = f"{val['verdict']} & {trend_word}"

    # confidence: lean on the valuation confidence, but downgrade if valuation
    # and trend openly disagree (e.g. cheap but falling = value trap risk).
    conflict = (val["score"] > 0 > bias["net"]) or (val["score"] < 0 < bias["net"])
    confidence = val["confidence"]
    if conflict and confidence == "High":
        confidence = "Medium"
    if conflict:
        summary += " — signals conflict (watch for a value trap or a momentum fade)"

    return {"stance": stance, "summary": summary,
            "confidence": confidence, "combined": combined}


def _explain(reason: str) -> str:
    """Pull the plain-English half out of a reason string (the bit after the dash)."""
    for sep in [" — ", " -> ", " – "]:
        if sep in reason:
            return reason.split(sep)[-1].strip().rstrip(".")
    return reason.rstrip(".")


def _join(reasons) -> str:
    """Join a few explanations into readable prose."""
    parts = [_explain(r) for r in reasons]
    parts = [(p[0].lower() + p[1:]) if p else p for p in parts]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 2 else " and ".join(parts)


def why_summary(snap: dict, bias: dict, val: dict, overall: dict) -> str:
    """A plain-English paragraph explaining the verdict -- the 'bottom line'."""
    name = snap.get("name") or snap.get("ticker")
    s = [f"**{name}** screens as **{val['verdict']}** with an overall "
         f"**{overall['stance']}** ({overall['confidence'].lower()} confidence)."]

    up, fv = val.get("upside"), val.get("fair_value")
    if up is not None and fv:
        direction = "upside to" if up > 0 else "downside to"
        tail = f" across {snap['n_analysts']} analysts." if snap.get("n_analysts") else "."
        s.append(f"Wall Street's consensus points to {up:+.0%} {direction} a "
                 f"${fv:,.0f} price target{tail}")

    if val["verdict"] == "Undervalued" and val["cheap"]:
        s.append(f"It looks cheap because {_join(val['cheap'][:3])}.")
    elif val["verdict"] == "Overvalued" and val["rich"]:
        s.append(f"It looks expensive because {_join(val['rich'][:3])}.")
    else:
        if val["cheap"]:
            s.append(f"In its favor: {_join(val['cheap'][:2])}.")
        if val["rich"]:
            s.append(f"Against it: {_join(val['rich'][:2])}.")

    trend = {
        "LONG": "The price trend is firmly up (above its 50- and 200-day averages).",
        "LEAN LONG": "The price trend leans up.",
        "NEUTRAL": "The price trend is mixed.",
        "LEAN SHORT": "The price trend leans down.",
        "SHORT": "The price trend is down (below its key moving averages).",
    }.get(bias["lean"], "")
    if trend:
        s.append(trend)

    if "conflict" in overall["summary"]:
        s.append("⚠️ Valuation and trend disagree — classic value-trap territory; "
                 "patient investors often wait for the trend to turn before buying a cheap-but-falling name.")
    elif overall["stance"] == "BUY LEAN":
        s.append("Net: cheap-enough and working — the kind of setup worth a closer look (still not advice).")
    elif overall["stance"] == "AVOID LEAN":
        s.append("Net: expensive and/or weak — little here to like right now.")

    return " ".join(s)


def build_board(tickers) -> list:
    """Run the FULL engine (valuation + trend + overall stance) across a list of
    tickers and return one row per name -- for the Watchlist board.

    Uses light snapshots (no news/earnings-history) because those aren't needed
    for the verdict, which keeps a 20-name board fast. One bad ticker is skipped,
    never crashes the board.
    """
    from analyst import get_snapshot, compute_bias

    rows = []
    for tk in tickers:
        try:
            snap = get_snapshot(tk, light=True)
            if not (snap.get("price") or snap.get("current_price")):
                continue                       # invalid/empty ticker -> skip
            bias = compute_bias(snap)
            val = value_verdict(snap)
            ov = overall_verdict(snap, bias, val)
            rows.append({
                "Ticker": tk,
                "Name": snap.get("name"),
                "Price": snap.get("price") or snap.get("current_price"),
                "Stance": ov["stance"],
                "Valuation": val["verdict"],
                "Upside %": round(val["upside"] * 100, 1) if val["upside"] is not None else None,
                "Trend": bias["lean"],
                "Confidence": ov["confidence"],
                "_score": ov["combined"],
            })
        except Exception:
            continue
    return rows


if __name__ == "__main__":
    import sys
    from analyst import get_snapshot, compute_bias
    tk = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    snap = get_snapshot(tk)
    bias = compute_bias(snap)
    val = value_verdict(snap)
    overall = overall_verdict(snap, bias, val)
    print(f"\n{snap['name']} ({tk})")
    print(f"VALUATION: {val['verdict']}  (confidence {val['confidence']}, "
          f"fair value ${_num(val['fair_value'])}, upside "
          f"{val['upside']:+.0%})" if val['upside'] is not None else
          f"VALUATION: {val['verdict']}")
    print(f"OVERALL:   {overall['stance']}  — {overall['summary']}  "
          f"[confidence {overall['confidence']}]")
    print("\nCheap because:")
    for r in val["cheap"]:
        print("  +", r)
    print("Rich because:")
    for r in val["rich"]:
        print("  -", r)
