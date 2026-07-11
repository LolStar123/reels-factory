"""Cost & usage ledger (module 20) + per-stage estimates (GEMINI-12)- one ledger, warn at 80%.

Free-first: piper/pyttsx3/matplotlib/ffmpeg cost nothing; entries land only when paid
APIs actually fire. Cost-per-follower computes once module 15 has performance numbers.
"""
from __future__ import annotations

import json
from datetime import date

from theme import ROOT

COSTS = ROOT / "state" / "costs.json"
MONTHLY_CAP_USD = 30.0
# per-call estimates (USD)- updated when bills arrive
EST = {"llm_extract": 0.02, "llm_script": 0.01, "llm_factcheck": 0.005,
       "elevenlabs_reel": 0.10, "ig_api": 0.0}


def _load() -> dict:
    if COSTS.exists():
        return json.loads(COSTS.read_text(encoding="utf-8"))
    return {"schema_version": 1, "entries": []}


def record(stage: str, kind: str, usd: float | None = None, note: str = ""):
    d = _load()
    d["entries"].append({"date": date.today().isoformat(), "stage": stage, "kind": kind,
                         "usd": usd if usd is not None else EST.get(kind, 0.0), "note": note})
    COSTS.write_text(json.dumps(d, indent=1), encoding="utf-8")
    spent = month_spend()
    if spent > MONTHLY_CAP_USD * 0.8:
        print(f"COSTS WARNING: ${spent:.2f} of ${MONTHLY_CAP_USD:.0f} monthly cap (80%+)")


def month_spend() -> float:
    d = _load()
    this_month = date.today().isoformat()[:7]
    return sum(e["usd"] for e in d["entries"] if e["date"].startswith(this_month))


def cost_per_follower() -> float | None:
    perf = json.loads((ROOT / "state" / "performance.json").read_text(encoding="utf-8"))
    follows = sum(p.get("follows", 0) for p in perf.get("posts", []))
    total = sum(e["usd"] for e in _load()["entries"])
    return round(total / follows, 4) if follows else None
