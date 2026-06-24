"""
llm.py  --  the AI analyst layer.

Takes the FACTS we already computed (snapshot + bias scorecard + news) and asks
Claude to write a balanced bull/bear thesis around them.

DESIGN PRINCIPLE (why this isn't a gimmick): the model is a WRITER, not an
oracle. We hand it our numbers and headlines and tell it to synthesize ONLY
those -- not to invent data or predict prices. That keeps it grounded and
defensible, which is exactly what an equity-research note must be.

Needs an Anthropic API key. Either set the env var ANTHROPIC_API_KEY, or pass
the key in from the app's sidebar. No key -> the app just skips this section.
"""

import os

# Default model. Sonnet 4.6 = strong writing at a sensible cost. Swap to
# "claude-opus-4-8" for max quality or "claude-haiku-4-5-20251001" for cheapest.
DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM = (
    "You are a senior equity research analyst writing a concise, balanced note. "
    "Use ONLY the facts provided -- do not invent numbers, prices, or events, and "
    "do not predict future prices. Structure the note as: a one-sentence summary, "
    "then '**Bull case**' (2-4 bullets), '**Bear case**' (2-4 bullets), then "
    "'**Net read**' (2-3 sentences tying it to the stated lean and what would "
    "change your mind). Be specific and cite the given metrics. Stay under 350 "
    "words. End with the exact line: '_Not investment advice._'"
)


def thesis_available(api_key: str | None = None) -> bool:
    """True if we have a key to call the API with."""
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))


def _build_prompt(snap: dict, bias: dict) -> str:
    """Flatten our computed facts into a clean text block for the model."""
    lines = [
        f"Company: {snap['name']} ({snap['ticker']})",
        f"Sector / Industry: {snap.get('sector')} / {snap.get('industry')}",
        "",
        "QUANT SCORECARD (computed by our rules engine):",
        f"  Overall lean: {bias['lean']} (bull score {bias['bull_score']} vs bear {bias['bear_score']})",
        "  Bull signals:",
    ]
    lines += [f"    - {r}" for r in bias["bull"]] or ["    (none)"]
    lines.append("  Bear signals:")
    lines += [f"    - {r}" for r in bias["bear"]] or ["    (none)"]

    lines += [
        "",
        "KEY METRICS:",
        f"  Price: {snap.get('price')}, 12-mo return: {snap.get('mom_12m')}",
        f"  P/E: {snap.get('pe')}, P/B: {snap.get('pb')}, P/S: {snap.get('ps')}",
        f"  ROE: {snap.get('roe')}, Net margin: {snap.get('margin')}, Debt/Equity: {snap.get('de')}",
        f"  Revenue growth: {snap.get('rev_growth')}, Earnings growth: {snap.get('earn_growth')}",
        f"  Next earnings: {snap.get('next_earnings')}",
        "",
        "RECENT NEWS HEADLINES:",
    ]
    for n in (snap.get("news") or [])[:6]:
        lines.append(f"  - {n.get('title')} ({n.get('publisher')})")
        if n.get("summary"):
            lines.append(f"      {n['summary'][:200]}")

    lines.append("\nWrite the research note now.")
    return "\n".join(lines)


def write_thesis(snap: dict, bias: dict, api_key: str | None = None,
                 model: str = DEFAULT_MODEL) -> str:
    """Call Claude and return the thesis text. Raises if the call fails."""
    from anthropic import Anthropic     # imported here so the app loads w/o a key

    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model,
        max_tokens=900,
        system=SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(snap, bias)}],
    )
    # A message's content is a list of blocks; for plain text it's one text block.
    return "".join(block.text for block in resp.content if block.type == "text")
