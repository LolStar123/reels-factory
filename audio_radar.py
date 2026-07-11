"""Trending-audio radar (module 21)- trending audio is a MANUAL in-app layer, so hand
the pick to the poster: per-vertical signature audio + rising options into caption.txt.

Researched seed (the PRD's): "Succession (Main Title Theme)" by Nicholas Britell- THE
high-finance sound, huge as trending audio. Signature for @priced.in; rotation for Overfit.
"""
from __future__ import annotations

import json
from datetime import date

from theme import ROOT, config

RADAR = ROOT / "state" / "audio_radar.json"

SEEDS = {
    "high_finance": [
        {"track": "Succession (Main Title Theme) - Nicholas Britell",
         "why": "the high-finance/old-money stereotype sound; strongly branded, proven trending",
         "how": "search 'Succession theme' in the IG audio picker at post time"},
    ],
    "wannabe_quant": [
        {"track": "Succession (Main Title Theme) - Nicholas Britell",
         "why": "rotation option- gravitas works for the quant lane too", "how": "IG audio picker"},
        {"track": "minimal tech / lo-fi bed from the in-app trending list",
         "why": "understated nerdy-tech reads as credible", "how": "browse IG trending audio > minimal"},
    ],
}


def _load() -> dict:
    if RADAR.exists():
        return json.loads(RADAR.read_text(encoding="utf-8"))
    return {"schema_version": 1, "picks": SEEDS, "updated": None}


def current_pick(vertical_key: str) -> str:
    d = _load()
    picks = d["picks"].get(vertical_key) or SEEDS.get(vertical_key, [])
    if not picks:
        return ""
    p = picks[0]
    return f"{p['track']} ({p['how']})"


def refresh() -> int:
    """Rising-audio detection needs a live logged-in session- until accounts exist this
    keeps the curated seed list fresh by hand-edit; the structure is ready for the scraper."""
    d = _load()
    d["updated"] = date.today().isoformat()
    RADAR.write_text(json.dumps(d, indent=1), encoding="utf-8")
    for v in config()["verticals"]:
        print(f"{v['key']}: {current_pick(v['key'])}")
    return 0
