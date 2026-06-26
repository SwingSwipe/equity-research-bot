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


def _fcf_yield(snap):
    fcf, mcap = snap.get("fcf"), snap.get("market_cap")
    return (fcf / mcap) if (fcf and mcap) else None


def _num(x, dec=0):
    return f"{x:,.{dec}f}" if isinstance(x, (int, float)) else "--"


def value_verdict(snap: dict) -> dict:
    """Return the valuation verdict dict for one stock's snapshot."""
    price = snap.get("price") or snap.get("current_price")
    cheap, rich = [], []          # (reason, weight)
    score = 0

    # --- 1. ANALYST PRICE TARGET (the headline fair-value anchor) ---
    tm = snap.get("target_mean")
    upside = (tm / price - 1) if (tm and price) else None
    if upside is not None:
        if upside > 0.15:
            cheap.append((f"Analyst mean target ${_num(tm)} is {upside:+.0%} above "
                          f"the ${_num(price,2)} price — Street sees upside.", 2)); score += 2
        elif upside < -0.05:
            rich.append((f"Price ${_num(price,2)} is above the ${_num(tm)} analyst "
                         f"target ({upside:+.0%}) — Street sees downside.", 2)); score -= 2

    # --- 2. ANALYST RATING ---
    rm = snap.get("rec_mean")     # 1=strong buy ... 5=sell
    if isinstance(rm, (int, float)) and rm > 0:
        if rm <= 2.2:
            cheap.append((f"Consensus rating {rm:.1f}/5 ({snap.get('rec_key')}) "
                          f"across {snap.get('n_analysts') or '?'} analysts — bullish.", 1)); score += 1
        elif rm >= 3.0:
            rich.append((f"Consensus rating {rm:.1f}/5 — analysts are cautious.", 1)); score -= 1

    # --- 3. PEG (value adjusted for growth) ---
    peg = snap.get("peg")
    if isinstance(peg, (int, float)) and peg > 0:
        if peg < 1.0:
            cheap.append((f"PEG {peg:.2f} (<1) — cheap relative to its growth.", 1)); score += 1
        elif peg > 2.0:
            rich.append((f"PEG {peg:.2f} (>2) — expensive relative to its growth.", 1)); score -= 1

    # --- 4. FORWARD vs TRAILING P/E ---
    fpe, tpe = snap.get("forward_pe"), snap.get("pe")
    if all(isinstance(x, (int, float)) and x > 0 for x in [fpe, tpe]):
        if fpe < tpe * 0.9:
            cheap.append((f"Forward P/E {fpe:.1f} below trailing {tpe:.1f} — earnings "
                          "expected to grow into the valuation.", 1)); score += 1
        elif fpe > tpe * 1.1:
            rich.append((f"Forward P/E {fpe:.1f} above trailing {tpe:.1f} — earnings "
                         "expected to shrink.", 1)); score -= 1

    # --- 5. FREE-CASH-FLOW YIELD ---
    fy = _fcf_yield(snap)
    if fy is not None:
        if fy > 0.05:
            cheap.append((f"Free-cash-flow yield {fy:.1%} — strong cash return for the price.", 1)); score += 1
        elif 0 < fy < 0.02:
            rich.append((f"Free-cash-flow yield only {fy:.1%} — you pay a lot per dollar of cash.", 1)); score -= 1

    # --- 6. EV/EBITDA (rough, sector-dependent) ---
    ee = snap.get("ev_ebitda")
    if isinstance(ee, (int, float)) and ee > 0:
        if ee < 10:
            cheap.append((f"EV/EBITDA {ee:.1f} (<10) — inexpensive on cash earnings.", 1)); score += 1
        elif ee > 20:
            rich.append((f"EV/EBITDA {ee:.1f} (>20) — richly valued on cash earnings.", 1)); score -= 1

    # --- verdict ---
    if score >= 3:
        verdict = "Undervalued"
    elif score <= -3:
        verdict = "Overvalued"
    else:
        verdict = "Fairly Valued"

    # --- confidence: agreement of lenses + analyst coverage ---
    n_signals = len(cheap) + len(rich)
    agreement = abs(score) / n_signals if n_signals else 0
    n_analysts = snap.get("n_analysts") or 0
    if n_signals >= 4 and agreement >= 0.6 and n_analysts >= 12:
        confidence = "High"
    elif n_signals >= 3 and agreement >= 0.4:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "verdict": verdict, "score": score, "confidence": confidence,
        "fair_value": tm, "upside": upside,
        "cheap": [r for r, _ in cheap], "rich": [r for r, _ in rich],
        "n_signals": n_signals,
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
