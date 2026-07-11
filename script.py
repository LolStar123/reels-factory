"""Scriptwriter- insight -> 20-45s reel script with beat timings.

Hook structures come from state/hook_bank.json weighted by score (stage-0 seeds + stage-12 re-scoring).
LLM polish when a key is present; a deterministic template path keeps --dry-run self-contained.
"""
from __future__ import annotations

import json
import os
import random

from contracts import BacktestResult, Insight, Script, StrategySpec
from theme import ROOT, config

HOOK_BANK = ROOT / "state" / "hook_bank.json"
WPS = 2.6  # spoken words/second- used to estimate beat durations


def _pick_hook(insight: Insight) -> tuple[str, str]:
    """Weighted pick from the hook bank, filtered by lane. Returns (hook_id, rendered hook)."""
    with open(HOOK_BANK, encoding="utf-8") as f:
        bank = json.load(f)
    cands = [h for h in bank["hooks"] if h.get("lane", "both") in (insight.lane, "both")]
    if not cands:
        return "fallback", insight.hook_idea
    rng = random.Random(insight.title)  # deterministic per topic
    weights = [max(h.get("score", 1.0), 0.05) for h in cands]
    chosen = rng.choices(cands, weights=weights, k=1)[0]
    return chosen["id"], insight.hook_idea  # structure guides; wording stays ours


def _estimate(text: str) -> float:
    return max(1.6, len(text.split()) / WPS)


def _fit_beats(hook: str, beats: list[str], cta: str, target: float) -> tuple[list[str], list[tuple[float, float]], float]:
    """Assign start/end seconds per element; trim beats if over 45s, keep if within bounds."""
    while True:
        durs = [_estimate(hook)] + [_estimate(b) for b in beats] + [_estimate(cta)]
        total = sum(durs) + 1.5  # breathing room
        if total <= 45 or len(beats) <= 2:
            break
        beats = beats[:-1]  # auto-trim least-essential trailing beat
    timings, t = [], 0.0
    for d in durs:
        timings.append((round(t, 2), round(t + d, 2)))
        t += d
    return beats, timings, round(t + 1.5, 1)


def write_script(insight: Insight, result: BacktestResult, spec: StrategySpec,
                 offline: bool = False) -> Script:
    cfg = config()
    m = result.metrics
    hook_id, _ = _pick_hook(insight)

    # deterministic template path (also the no-key --dry-run path)
    # digits, never number-words ("12", "$65,600", "24%")- easier to read on screen,
    # and every modern TTS engine normalises them correctly in speech.
    # Hook: 3-second rule (social-content skill)- BIG money number as the visual hook +
    # <=10 readable words, money stakes, zero jargon on the high_finance surface.
    rule = spec.plain_rule or _tight(spec.signal_rule, 130)
    gap = m["benchmark_final"] - m["final_value"]
    years = result.window.split("-")
    span = f"{int(years[-1]) - int(years[0])} years" if len(years) == 2 else "20 years"

    if insight.tone == "confirm":
        hook_number = f"+{_money(abs(gap))}" if gap < 0 else f"{m['sharpe']:.2f} Sharpe"
        hook = "The famous strategy that actually survives testing."
    elif insight.tone == "surprise":
        hook_number = f"{abs(m['mdd']) * 100:.0f}% vs {abs(m['benchmark_mdd']) * 100:.0f}%" \
            if "benchmark_mdd" in m else _money(m["final_value"])
        hook = "It lost to the market. It might still be smarter."
    else:  # debunk
        hook_number = f"-{_money(abs(gap))}" if gap > 0 else _money(m["final_value"])
        hook = "What Wall Street's favourite rule leaves on the table."

    # the feel-smart payoff: the evidence-picked, recency-rotated insider term (insight engine)
    smart = insight.smart_line or "The pros judge on risk-adjusted return- not what it made, but what it cost to make."
    dd_coda = f" And it rode a {abs(m['mdd']) * 100:.0f}% drop on the way." \
        if insight.smart_term not in ("drawdown tolerance", "risk-adjusted return") else ""
    beats = [
        f"The rule is simple: {rule}",
        f"Over {span}, $10,000 became {_money(m['final_value'])}. "
        f"Just buying the market made {_money(m['benchmark_final'])}.",
        f"{smart}{dd_coda}",
    ]
    if insight.tone == "confirm":
        beats[2] = f"{smart} Drawdown {abs(m['mdd']) * 100:.0f}%- know it before you copy it."
    cta = "Follow for the next test- most strategies don't survive it."

    if not offline and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            hook, beats, cta = _llm_polish(insight, result, spec, hook, beats, cta)
        except Exception:
            pass  # template stands- never block a reel on the LLM

    beats, timings, est = _fit_beats(hook, beats, cta, cfg["video"]["target_seconds"])
    disclaimer = cfg["compliance"]["hard_disclaimer"]
    caption = (f"{insight.hook_idea} {result.vs_benchmark}. "
               f"Paper: {spec.paper_ref}. {disclaimer}")
    return Script(
        hook=hook, hook_number=hook_number, beats=beats, cta=cta,
        on_screen_text=[hook] + beats + [cta],
        caption=caption,
        hashtags=["#investing", "#quant", "#backtest", "#finance", "#fintok"],
        est_seconds=est, beat_timings=timings,
        cites_paper=spec.paper_ref, hook_id=hook_id,
    )


def _short_claim(claim: str) -> str:
    return claim if len(claim) < 60 else claim[:57] + "..."


def _tight(text: str, n: int) -> str:
    """Trim a rule statement to n chars at a word boundary for spoken pace."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;")
    return cut + "."


def _money(v: float) -> str:
    """Digits + symbol, rounded to the hundred- '$65,600', never 'sixty-five thousand dollars'."""
    sym = config()["brand"].get("currency", {}).get("symbol", "$")
    return f"{sym}{round(v / 100) * 100:,.0f}"


def _llm_polish(insight, result, spec, hook, beats, cta):
    import anthropic
    client = anthropic.Anthropic()
    cfg = config()
    prompt = (f"Rewrite this finance-reel script. Voice: {cfg['brand']['voice']}. Lane: {insight.lane}. "
              f"Tone: {insight.tone}. Keep EVERY number exactly as given- they are measured facts. "
              f"Return JSON {{\"hook\": str, \"beats\": [str], \"cta\": str}} only.\n"
              f"hook: {hook}\nbeats: {json.dumps(beats)}\ncta: {cta}")
    msg = client.messages.create(model="claude-sonnet-5", max_tokens=800,
                                 messages=[{"role": "user", "content": prompt}])
    raw = msg.content[0].text
    obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    return obj["hook"], obj["beats"], obj["cta"]
