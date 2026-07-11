"""A/B experimentation framework (module 16)- one deliberate variable at a time.

Register an experiment (hook / cover / length / post-time), tag the reels, judge on the
north-star once both arms have numbers, feed the winner back into the hook bank.
Live-account gated: judging needs stage-12 data.
"""
from __future__ import annotations

import json
from datetime import date

from theme import ROOT, config

EXP = ROOT / "state" / "experiments.json"


def _load() -> dict:
    if EXP.exists():
        return json.loads(EXP.read_text(encoding="utf-8"))
    return {"schema_version": 1, "experiments": []}


def _save(d):
    EXP.write_text(json.dumps(d, indent=1), encoding="utf-8")


def register(name: str, variable: str, arm_a: str, arm_b: str) -> dict:
    d = _load()
    exp = {"name": name, "variable": variable, "arms": {"A": arm_a, "B": arm_b},
           "reels": {"A": [], "B": []}, "opened": date.today().isoformat(),
           "winner": None}
    d["experiments"].append(exp)
    _save(d)
    return exp


def tag_reel(exp_name: str, arm: str, slug: str):
    d = _load()
    for e in d["experiments"]:
        if e["name"] == exp_name and e["winner"] is None:
            e["reels"][arm].append(slug)
    _save(d)


def judge() -> list[str]:
    """Score open experiments against the north-star; declare winners with >= 3 reels/arm."""
    perf = json.loads((ROOT / "state" / "performance.json").read_text(encoding="utf-8"))
    score = {p["slug"]: (p.get("avg_watch_time_ratio") or 0) * 100 + (p.get("saves") or 0) * 2
             + (p.get("follows") or 0) * 5 for p in perf.get("posts", [])}
    d = _load()
    decided = []
    for e in d["experiments"]:
        if e["winner"]:
            continue
        arms = {}
        for arm, slugs in e["reels"].items():
            vals = [score[s] for s in slugs if s in score]
            if len(vals) >= 3:
                arms[arm] = sum(vals) / len(vals)
        if len(arms) == 2:
            e["winner"] = max(arms, key=arms.get)
            e["decided"] = date.today().isoformat()
            decided.append(f"{e['name']}: arm {e['winner']} wins ({e['arms'][e['winner']]})")
    _save(d)
    return decided
