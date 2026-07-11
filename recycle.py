"""Evergreen recycler & cross-poster (module 22)- squeeze the winners.

After N days, re-surface top performers (fresh hook/cover, same backtest- the research
is the expensive bit) and queue lag-posts for the other platforms. Live-account gated.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import ledger
from theme import ROOT, config

RECYCLE_AFTER_DAYS = 21
QUEUE = ROOT / "state" / "recycle_queue.json"


def find_candidates(top_k: int = 5) -> list[dict]:
    perf = json.loads((ROOT / "state" / "performance.json").read_text(encoding="utf-8"))
    posts = perf.get("posts", [])
    cutoff = (date.today() - timedelta(days=RECYCLE_AFTER_DAYS)).isoformat()
    old = [p for p in posts if p.get("date", "9999") <= cutoff]
    ranked = sorted(old, key=lambda p: (p.get("follows", 0), p.get("saves", 0)), reverse=True)
    return ranked[:top_k]


def queue_recycles() -> int:
    q = json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else \
        {"schema_version": 1, "queue": []}
    queued = {e["slug"] for e in q["queue"]}
    n = 0
    for cand in find_candidates():
        if cand["slug"] in queued:
            continue
        q["queue"].append({
            "slug": cand["slug"], "reason": f"{cand.get('follows', 0)} follows / {cand.get('saves', 0)} saves",
            "actions": ["fresh hook variant (hook bank)", "new cover (module 17)",
                        "repost to " + ", ".join(config()["distribution"]["repurpose"][1:])],
            "queued": date.today().isoformat(), "done": False})
        n += 1
    QUEUE.write_text(json.dumps(q, indent=1), encoding="utf-8")
    return n


def repurpose_files(slug: str) -> dict:
    """One research run, five surfaces: same 9:16 mp4 + platform captions + an X thread draft."""
    d = ROOT / "out" / slug
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    m = meta["metrics"]
    thread = [
        f"{meta['hook']}",
        f"The test: {meta['paper_ref']} on {meta['window']} of real data.",
        f"Result: CAGR {m['cagr'] * 100:.1f}%, Sharpe {m['sharpe']:.2f}, max drawdown {m['mdd'] * 100:.0f}%.",
        f"Verdict: {meta['verdict']}. Full chart in the video.",
        "Educational only, not financial advice.",
    ]
    (d / "x_thread.txt").write_text("\n\n---\n\n".join(thread), encoding="utf-8")
    caption = (d / "caption.txt").read_text(encoding="utf-8").split("\nALT TEXT")[0]
    for platform in ("youtube_short", "tiktok"):
        (d / f"caption_{platform}.txt").write_text(caption[:2000], encoding="utf-8")
    return {"thread": str(d / "x_thread.txt"), "captions": ["youtube_short", "tiktok"]}
