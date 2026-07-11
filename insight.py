"""Insight engine- backtest result -> the reel's angle, lane, tone (with variety enforcement, NICHE 4)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from contracts import BacktestResult, Insight, StrategySpec
from theme import ROOT, config

USED_TOPICS = ROOT / "state" / "used_topics.json"

# chart routing per lane (CHART & VISUAL LIBRARY)
_LANE_CHARTS = {
    "high_finance": ["equity_race", "final_value_bars", "signal_overlay", "what_if_ticker"],
    "wannabe_quant": ["equity_race", "underwater", "rolling_sharpe", "vol_surface", "kelly", "monte_carlo"],
}


def _route_lane(spec: StrategySpec) -> str:
    """Topic-slice routing: technical/quanty shapes -> wannabe_quant, accessible tests -> high_finance."""
    quanty = {"pairs", "vol", "factor_sort"}
    text = f"{spec.name} {spec.hypothesis} {spec.signal_rule}".lower()
    quant_kw = ("volatility", "sharpe", "kelly", "black-scholes", "greeks", "factor", "stat-arb",
                "implied", "surface", "z-score", "cross-sectional")
    if spec.shape in quanty or any(k in text for k in quant_kw):
        return "wannabe_quant"
    return "high_finance"


def _recent_tones(n: int = 6) -> list[str]:
    try:
        with open(USED_TOPICS, encoding="utf-8") as f:
            d = json.load(f)
        entries = [e for v in d.get("by_vertical", {}).values() for e in v]
        entries.sort(key=lambda e: e.get("date", ""))
        return [e.get("tone", "debunk") for e in entries[-n:]]
    except Exception:
        return []


def is_repeat(paper_ref: str, window_days: int = 30) -> bool:
    try:
        with open(USED_TOPICS, encoding="utf-8") as f:
            d = json.load(f)
        cutoff = (date.today() - timedelta(days=window_days)).isoformat()
        for v in d.get("by_vertical", {}).values():
            for e in v:
                if e.get("paper_ref") == paper_ref and e.get("date", "") >= cutoff:
                    return True
    except Exception:
        pass
    return False


def mark_used(paper_ref: str, lane: str, tone: str):
    with open(USED_TOPICS, encoding="utf-8") as f:
        d = json.load(f)
    d["by_vertical"].setdefault(lane, []).append(
        {"paper_ref": paper_ref, "tone": tone, "date": date.today().isoformat()})
    with open(USED_TOPICS, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


# ── the insider-term bank: one concept per reel, picked by EVIDENCE, rotated by recency ──
# Each entry: (id, applies(result, spec), line). Lines stay <=22 words, digits not words.
def _term_bank(spec: StrategySpec, result) -> list[tuple[str, bool, str]]:
    m = result.metrics
    exposure = float((result.trades_summary or {}).get("avg_gross_exposure", 1.0))
    dd = abs(m["mdd"]) * 100
    return [
        ("implementation gap",
         "cost" in (result.claimed_result or "").lower() or m["sharpe"] < m.get("benchmark_sharpe", 0),
         "Quants call that the implementation gap- the paper never pays commissions or slippage. You would."),
        ("whipsaw",
         spec.shape in ("crossover", "momentum"),
         "Traders call those false signals whipsaw- every fakeout crossing costs you twice: once out, once back in."),
        ("cash drag",
         exposure < 0.85,
         f"That's cash drag- this rule sat out of the market so often that missed rallies cost more than dodged dips."),
        ("survivorship bias",
         result.survivorship_limited,
         "And free data has survivorship bias- dead stocks vanish from history, making every backtest look kinder than life."),
        ("drawdown tolerance",
         dd >= 20,
         f"Quants call it drawdown tolerance- returns you brag about, but a {dd:.0f}% drop is what you actually live through."),
        ("regime dependence",
         result.verdict == "broke down out-of-sample",
         "That's regime dependence- an edge tuned to one era that dies the moment the market changes character."),
        ("overfitting",
         len(spec.params) >= 4,
         "Quants call it overfitting- enough knobs and any backtest looks like genius. Fresh data is the judge."),
        ("out-of-sample survival",
         result.verdict == "held up",
         "Quants call this out-of-sample survival- almost nothing keeps working on data it never saw. This did."),
        ("risk-adjusted return",
         True,  # always-applicable fallback
         f"The pros judge on risk-adjusted return- not what it made, but what it made per unit of pain. Here: {m['sharpe']:.2f}."),
    ]


def pick_smart_term(spec: StrategySpec, result) -> tuple[str, str]:
    """Most-relevant applicable term the account hasn't used recently."""
    try:
        with open(USED_TOPICS, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    recent = d.get("recent_terms", [])[-4:]
    applicable = [(tid, line) for tid, ok, line in _term_bank(spec, result) if ok]
    fresh = [(tid, line) for tid, line in applicable if tid not in recent] or applicable
    return fresh[0]


def _mark_term(term: str):
    with open(USED_TOPICS, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("recent_terms", []).append(term)
    d["recent_terms"] = d["recent_terms"][-8:]
    with open(USED_TOPICS, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def build_insight(spec: StrategySpec, result: BacktestResult) -> Insight:
    m = result.metrics
    lane = _route_lane(spec)

    # tone from the claim-vs-reality gap, then variety-forced (never all takedowns)
    tone = {"held up": "confirm", "underwhelmed": "debunk", "broke down out-of-sample": "debunk"}[result.verdict]
    recent = _recent_tones()
    if tone == "debunk" and len(recent) >= 4 and all(t == "debunk" for t in recent[-4:]):
        # 4 debunks in a row- reframe this one as a surprise angle instead of another takedown
        tone = "surprise"

    gap_line = (f"paper claimed {result.claimed_result}; measured Sharpe {m['sharpe']:.2f}, "
                f"CAGR {m['cagr'] * 100:.1f}%" if result.claimed_result else
                f"measured Sharpe {m['sharpe']:.2f}")
    hooks = {
        "debunk": f"A paper said this works. I tested {result.window}. Here's what it really made.",
        "confirm": "Most viral strategies fail my backtest. This one didn't.",
        "surprise": f"This strategy underperformed the market- and it might still be the smarter hold.",
    }
    key_points = [
        f"The rule: {spec.signal_rule}",
        f"$10k -> ${m['final_value']:,.0f} over {result.window} ({result.vs_benchmark})",
        f"Max drawdown {m['mdd'] * 100:.0f}% vs benchmark {m['benchmark_mdd'] * 100:.0f}%",
        gap_line,
    ]
    if result.survivorship_limited:
        key_points.append("Caveat: free-data backtest- survivorship-limited, treat as indicative")

    chart_type = "equity_race"  # hero visual; registry rotates via planner in steady state
    term, term_line = pick_smart_term(spec, result)
    _mark_term(term)
    return Insight(
        title=spec.name,
        angle=f"{tone}: {result.verdict}- {result.vs_benchmark}",
        hook_idea=hooks[tone],
        key_points=key_points,
        chart_type=chart_type,
        risk_flag=result.verdict != "held up",
        lane=lane,
        tone=tone,
        smart_term=term,
        smart_line=term_line,
    )
