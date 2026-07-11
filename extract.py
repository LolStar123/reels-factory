"""Strategy extractor- paper text -> StrategySpec via a constrained DSL (CODEX-4/GEMINI-7).

LLM-backed when ANTHROPIC_API_KEY is present; --dry-run uses the bundled hand-derived spec.
The codeability gate rejects specs the shape executors can't run BEFORE the data layer spends effort.
"""
from __future__ import annotations

import json
import os

from contracts import Paper, StrategySpec
from theme import ROOT

SAMPLE_SPEC = ROOT / "assets" / "sample" / "sample_strategy_spec.json"

_EXTRACT_PROMPT = """You are a quant-research engineer. Reduce this paper to ONE mechanically
testable trading strategy as JSON matching this schema exactly (no prose, JSON only):
{{"name": str, "hypothesis": str,
  "shape": one of ["momentum","mean_reversion","crossover","pairs","calendar","factor_sort","vol"],
  "universe": [tickers- liquid ETFs/large caps proxying the paper's universe],
  "signal_rule": str, "params": dict (shape params- momentum: lookback_m/skip_m/long_short/cross_sectional/top_fraction;
  mean_reversion: lookback_d/entry_z/exit_z; crossover: fast_d/slow_d; pairs: lookback_d/entry_z/max_hold_d;
  calendar: window in [turn_of_month, monday, month_days] + days; factor_sort: metric/lookback_d/top_fraction;
  vol: target_vol/lookback_d/max_leverage),
  "entry": str, "exit": str, "rebalance": one of ["daily","weekly","monthly"],
  "position_sizing": str, "lookback": str, "claimed_result": str (the paper's headline claim), "paper_ref": str,
  "plain_rule": str (ONE sentence a 16-year-old understands- no jargon, digits not number-words,
  e.g. "If it went up over the last 12 months, you buy. If it went down, you sit in cash."),
  "display_title": str (a short viewer-facing name like "The 12-Month Trend Rule"- never the lab label)}}
If the paper cannot be reduced to a mechanical rule testable on daily OHLCV bars, return {{"codeable": false, "reason": str}}.

PAPER TITLE: {title}
PAPER TEXT (truncated):
{text}
"""

# few-shot grounding: the quantihack repo is the validation set (PRD PRIOR ART #2)
_FEWSHOT = ("Example- Ariel (1990) holiday effect -> "
            '{"shape":"calendar","universe":["SPY"],"params":{"window":"turn_of_month"},"rebalance":"daily",...}. '
            "Example- Jegadeesh momentum -> "
            '{"shape":"momentum","universe":["SPY","TLT","GLD","XLF","XLK"],"params":{"lookback_m":12,"skip_m":1,'
            '"cross_sectional":true,"top_fraction":0.3},"rebalance":"monthly",...}.')


def codeability_gate(spec: StrategySpec) -> tuple[bool, str]:
    """Cheap gate between extract and data (CODEX-4): can the executors actually run this?"""
    from backtest import SHAPES
    if spec.shape not in SHAPES:
        return False, f"unknown shape {spec.shape}"
    if not spec.universe:
        return False, "empty universe"
    if spec.shape == "pairs" and len(spec.universe) < 2:
        return False, "pairs needs 2 tickers"
    if spec.rebalance not in ("daily", "weekly", "monthly"):
        return False, f"bad rebalance {spec.rebalance}"
    return True, "ok"


def bundled_sample_spec() -> StrategySpec:
    with open(SAMPLE_SPEC, encoding="utf-8") as f:
        return StrategySpec(**json.load(f))


def extract_strategy(paper: Paper, offline: bool = False) -> StrategySpec | None:
    """Paper -> StrategySpec, or None if not mechanically testable (logged by caller)."""
    if offline or not os.environ.get("ANTHROPIC_API_KEY"):
        # keyless path: only the bundled sample paper is extractable
        if "1404.3274" in (paper.id or "") or "Trend Following" in paper.title:
            return bundled_sample_spec()
        return None
    import anthropic
    client = anthropic.Anthropic()
    text = (paper.full_text or paper.abstract or "")[:60_000]
    msg = client.messages.create(
        model="claude-sonnet-5", max_tokens=1500,
        system="You reduce academic finance papers to mechanical strategy specs. " + _FEWSHOT,
        messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(title=paper.title, text=text)}])
    raw = msg.content[0].text.strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    obj = json.loads(raw)
    if obj.get("codeable") is False:
        return None
    obj.setdefault("paper_ref", f"{paper.title} ({paper.year})")
    spec = StrategySpec(**obj)
    ok, reason = codeability_gate(spec)
    if not ok:
        spec.codeable = False
    return spec if spec.codeable else None
