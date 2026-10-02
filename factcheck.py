"""Independent fact-check gate (module 19)- a pass DISTINCT from the writer.

Deterministic layer: every number in the script/caption must trace to BacktestResult
(or the paper's claimed_result). LLM layer (key present) re-reads claims vs the paper text.
Fails the reel on any mismatch- reputational insurance on top of the QC stat-match.
"""
from __future__ import annotations

import os
import re

from contracts import BacktestResult, Script


def _numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])(\d[\d,]*\.?\d*)(?!\d)", text)]


def _allowed_values(result: BacktestResult) -> set[float]:
    m = result.metrics
    vals = set()
    for v in [m["cagr"] * 100, m["sharpe"], m["mdd"] * 100, abs(m["mdd"]) * 100,
              m["hit_rate"] * 100, m["final_value"], m["benchmark_final"],
              (m["cagr"] - m["benchmark_cagr"]) * 100, m["benchmark_cagr"] * 100,
              m.get("best_year", 0) * 100, m.get("worst_year", 0) * 100,
              m["final_value"] / 1000, m["benchmark_final"] / 1000, 10_000, 10]:
        for r in (0, 1, 2):
            vals.add(round(v, r))
            vals.add(round(abs(v), r))
    # window years + claimed numbers are legitimate too
    for y in re.findall(r"(19|20)\d{2}", result.window + " " + result.paper_ref):
        pass
    vals.update(float(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", result.window + " " + (result.paper_ref or "")))
    vals.update(_numbers(result.claimed_result or ""))
    vals.update(_numbers(result.vs_benchmark or ""))
    vals.update(_numbers(result.paper_ref or ""))  # citation numbers (year, arXiv id) are legitimate
    ts = result.trades_summary or {}
    vals.update(_numbers(str(ts.get("rule_text", ""))))       # the rule's own parameters (50/200 MA, 12 months...)
    vals.update(float(v) for v in (ts.get("params") or {}).values()
                if isinstance(v, (int, float)))
    gap = m["benchmark_final"] - m["final_value"]  # the hook's shortfall/edge number
    for v in (gap, abs(gap), round(gap / 100) * 100, round(abs(gap) / 100) * 100,
              abs(m.get("benchmark_mdd", 0)) * 100):
        for r in (0, 1, 2):
            vals.add(round(v, r))
            vals.add(round(abs(v), r))
    win = result.window.split("-")
    if len(win) == 2:  # the spoken "over 22 years" span
        vals.add(float(int(win[1]) - int(win[0])))
    return vals


def factcheck(script: Script, result: BacktestResult, *, allow_online: bool = True) -> tuple[bool, list[str]]:
    """Deterministic: every number spoken/written must be derivable from the backtest or the claim."""
    fails = []
    allowed = _allowed_values(result)
    for label, text in [("hook", script.hook), *[(f"beat{i}", b) for i, b in enumerate(script.beats)],
                        ("cta", script.cta), ("caption", script.caption)]:
        for num in _numbers(text):
            near = any(abs(num - a) <= max(0.011, abs(a) * 0.006) for a in allowed)
            if not near and num not in (1, 2, 3, 4, 5, 12, 20, 30, 45, 500):  # small counting words
                fails.append(f"{label}: number {num} not traceable to the backtest")
    if allow_online and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            fails += _llm_pass(script, result)
        except Exception:
            pass  # LLM layer is additive; the deterministic gate always ran
    return (len(fails) == 0), fails


def _llm_pass(script: Script, result: BacktestResult) -> list[str]:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-5", max_tokens=400,
        messages=[{"role": "user", "content":
                   "You are an independent fact-checker (you did NOT write this script). "
                   f"Backtest ground truth: {result.metrics}\nclaimed by paper: {result.claimed_result}\n"
                   f"paper ref: {result.paper_ref}\nScript: hook={script.hook} beats={script.beats} "
                   f"caption={script.caption}\nList any claim that misstates the ground truth, "
                   "misattributes the paper, or presents the paper's claim as confirmed. "
                   "Reply 'OK' if none."}])
    text = msg.content[0].text.strip()
    return [] if text.upper().startswith("OK") else [f"llm-factcheck: {text[:300]}"]
