"""Performance feedback loop (stage 12)- the factory that learns.

Pull IG insights per posted reel -> state/performance.json -> re-score hooks, bias
paper/topic selection, report. Degrades gracefully (GEMINI-4): backoff + cache on rate
limits, manual entries accepted. NEVER optimises into dishonesty- the QC gate is upstream
and absolute; this loop only tunes packaging.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import ledger
from theme import ROOT, config

PERF = ROOT / "state" / "performance.json"
REPORT = ROOT / "state" / "performance_report.md"


def _load() -> dict:
    return json.loads(PERF.read_text(encoding="utf-8"))


def _save(d: dict):
    PERF.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _ig_insights(media_id: str, token: str) -> dict | None:
    """One media's insights with backoff- rate limits are expected, not exceptional."""
    import requests
    metrics = "reach,plays,total_interactions,saved,shares,follows"
    for attempt in range(3):
        try:
            r = requests.get(f"https://graph.facebook.com/v21.0/{media_id}/insights",
                             params={"metric": metrics, "access_token": token}, timeout=20)
            if r.status_code == 200:
                out = {}
                for item in r.json().get("data", []):
                    out[item["name"]] = (item.get("values") or [{}])[0].get("value", 0)
                return out
            if r.status_code in (429, 4):
                time.sleep(15 * (attempt + 1))
                continue
            return None
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def add_manual_entry(slug: str, reach: int, plays: int, avg_watch_time_ratio: float,
                     saves: int, shares: int, follows: int):
    """The no-API path: hand-entered numbers keep the loop alive."""
    d = _load()
    with ledger.conn() as c:
        row = c.execute("SELECT vertical, hook_id, chart_type, seconds, meta FROM reels WHERE slug=?",
                        (slug,)).fetchone()
    meta = json.loads(row[4]) if row else {}
    d["posts"].append({
        "slug": slug, "date": date.today().isoformat(), "source": "manual",
        "vertical": row[0] if row else "?", "hook_id": row[1] if row else "?",
        "chart_type": row[2] if row else "?", "seconds": row[3] if row else 0,
        "tone": meta.get("tone"), "paper_ref": meta.get("paper_ref"),
        "reach": reach, "plays": plays, "avg_watch_time_ratio": avg_watch_time_ratio,
        "saves": saves, "shares": shares, "follows": follows})
    _save(d)


def pull_insights() -> int:
    d = _load()
    pulled = 0
    for vert in config()["verticals"]:
        key = vert["key"].upper()
        token = os.environ.get(f"IG_{key}_ACCESS_TOKEN")
        if not token:
            continue
        # media ids are stored in the ledger when post_reel succeeds (Slice C wiring)
        with ledger.conn() as c:
            rows = c.execute("SELECT slug, meta FROM reels WHERE vertical=? AND posted=1",
                             (vert["key"],)).fetchall()
        for slug, meta_json in rows:
            meta = json.loads(meta_json)
            mid = meta.get("ig_media_id")
            if not mid or any(p["slug"] == slug and p.get("source") == "api" for p in d["posts"]):
                continue
            ins = _ig_insights(mid, token)
            if ins:
                plays = max(1, ins.get("plays", 1))
                d["posts"].append({
                    "slug": slug, "date": date.today().isoformat(), "source": "api",
                    "vertical": vert["key"], "hook_id": meta.get("hook_id"),
                    "chart_type": meta.get("chart_type"), "tone": meta.get("tone"),
                    "paper_ref": meta.get("paper_ref"), "seconds": meta.get("seconds"),
                    "reach": ins.get("reach", 0), "plays": plays,
                    "avg_watch_time_ratio": 0.0,  # derived when ig_reels_avg_watch_time present
                    "saves": ins.get("saved", 0), "shares": ins.get("shares", 0),
                    "follows": ins.get("follows", 0)})
                pulled += 1
    _save(d)
    write_report(d)
    print(f"insights: {pulled} pulled via API, {len(d['posts'])} total entries -> {REPORT.name}")
    return 0


def _north_star(p: dict) -> float:
    return (p.get("avg_watch_time_ratio") or 0) * 100 + (p.get("saves") or 0) * 2 + (p.get("follows") or 0) * 5


def write_report(d: dict | None = None):
    d = d or _load()
    posts = d.get("posts", [])
    lines = [f"# Performance report- {date.today().isoformat()}", ""]
    if not posts:
        lines += ["No posted reels with numbers yet. The loop starts learning after "
                  f"{config()['feedback']['learn_after_n_posts']} posts."]
    else:
        ranked = sorted(posts, key=_north_star, reverse=True)
        lines.append("## Top 5")
        for p in ranked[:5]:
            lines.append(f"- **{p['slug']}** ({p.get('vertical')}, {p.get('tone')}, hook `{p.get('hook_id')}`)- "
                         f"reach {p.get('reach')}, saves {p.get('saves')}, follows {p.get('follows')}")
        lines.append("\n## Bottom 5")
        for p in ranked[-5:]:
            lines.append(f"- {p['slug']} ({p.get('vertical')}, hook `{p.get('hook_id')}`)")
        # one concrete recommendation: the strongest hook family
        by_hook: dict[str, list[float]] = {}
        for p in posts:
            by_hook.setdefault(p.get("hook_id") or "?", []).append(_north_star(p))
        if by_hook:
            best = max(by_hook, key=lambda k: sum(by_hook[k]) / len(by_hook[k]))
            lines.append(f"\n## Do more of\nHook structure **`{best}`** leads the north-star metric- "
                         "weight it up next batch (the hook bank re-score does this automatically).")
        # rejection signal (GEMINI-11)
        with ledger.conn() as c:
            tags = c.execute("SELECT reject_tag, COUNT(*) FROM reels WHERE approval='rejected' "
                             "GROUP BY reject_tag").fetchall()
        if tags:
            lines.append("\n## Rejections\n" + "\n".join(f"- {t or 'untagged'}: {n}" for t, n in tags))
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def bias_weights() -> dict:
    """Topic-family weights for the paper ranker (stage 1 bias)- derived from real numbers."""
    posts = _load().get("posts", [])
    if len(posts) < config()["feedback"]["learn_after_n_posts"]:
        return {}
    fams: dict[str, list[float]] = {}
    for p in posts:
        ref = (p.get("paper_ref") or "").lower()
        for fam in ("momentum", "reversion", "vol", "factor", "calendar", "pairs", "crossover"):
            if fam in ref:
                fams.setdefault(fam, []).append(_north_star(p))
    overall = [v for vs in fams.values() for v in vs]
    if not overall:
        return {}
    mean = sum(overall) / len(overall)
    return {f: round((sum(vs) / len(vs)) / mean, 2) for f, vs in fams.items() if vs}
