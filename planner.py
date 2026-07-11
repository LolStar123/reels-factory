"""Content-pillar & series planner (module 18)- recurring recognisable series + variety.

Series give brand identity and bingeability; the variety guard stops over-indexing one
strategy family. The buffer is planned against the calendar per vertical.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

import ledger
from theme import ROOT, config

SERIES = {
    "high_finance": ["Paper vs Reality", "Myth-Busted", "The Drawdown Nobody Mentions"],
    "wannabe_quant": ["Paper vs Reality", "The Real Machinery", "Edge Autopsy"],
}


def assign_series(tone: str, lane: str) -> str:
    menu = SERIES.get(lane, SERIES["high_finance"])
    return {"debunk": menu[1] if len(menu) > 1 else menu[0],
            "confirm": menu[0], "surprise": menu[-1]}.get(tone, menu[0])


def variety_guard(candidate_family: str, lane: str, window: int = 10) -> bool:
    """False if this family already dominates the last N reels for the lane."""
    with ledger.conn() as c:
        rows = c.execute("SELECT paper_ref FROM reels WHERE vertical=? "
                         "ORDER BY created DESC LIMIT ?", (lane, window)).fetchall()
    fams = Counter()
    for (ref,) in rows:
        for fam in ("momentum", "reversion", "vol", "factor", "calendar", "pairs", "crossover"):
            if fam in (ref or "").lower():
                fams[fam] += 1
    return fams.get(candidate_family, 0) < max(3, window // 3)


def plan_buffer() -> dict:
    """Days of approved-but-unposted runway per vertical vs the buffer target."""
    cfg = config()
    target = cfg["distribution"]["buffer_target_days"]
    out = {}
    for v in cfg["verticals"]:
        have = ledger.buffer_count(v["key"])
        need_daily = v.get("posts_per_day", 2)
        days = have / need_daily if need_daily else 0
        out[v["key"]] = {"approved_unposted": have, "days_of_runway": round(days, 1),
                         "target_days": target, "short": days < target}
    return out
