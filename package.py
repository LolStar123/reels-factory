"""Packager- out/<slug>/ with the mp4, caption.txt, thumbnail, meta.json, and the
approval-pending flag. Posting via IG Graph API ONLY on explicit ledger approval.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import ledger
from contracts import BacktestResult, Insight, ReelPackage, Script
from theme import ROOT, config

OUT = ROOT / "out"


def make_slug(spec_name: str, vertical: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in spec_name.lower())[:48].strip("-")
    return f"{date.today().isoformat()}_{vertical}_{safe}"


def package_reel(slug: str, mp4: Path, thumb: Path | None, script: Script, insight: Insight,
                 result: BacktestResult, cap: dict, vertical: dict, qc_passed: bool,
                 qc_fails: list[str], run_id: str, chart_type: str, seconds: float,
                 music_track: str | None) -> ReelPackage:
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    final_mp4 = d / f"{slug}.mp4"
    shutil.copy2(mp4, final_mp4)
    thumb_path = ""
    if thumb and Path(thumb).exists():
        thumb_path = str(d / "cover.png")
        shutil.copy2(thumb, thumb_path)

    caption_txt = d / "caption.txt"
    lines = [cap["caption"], "", f"ALT TEXT: {cap['alt_text']}"]
    if cap.get("trending_audio_note"):
        lines += ["", f"SUGGESTED TRENDING AUDIO (add in-app at post time): {cap['trending_audio_note']}"]
    caption_txt.write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "slug": slug, "vertical": vertical["key"], "paper_ref": result.paper_ref,
        "claimed": result.claimed_result, "metrics": result.metrics, "verdict": result.verdict,
        "window": result.window, "as_of": result.as_of, "data_source": result.data_source,
        "survivorship_limited": result.survivorship_limited,
        "hook": script.hook, "hook_id": script.hook_id, "tone": insight.tone,
        "smart_term": insight.smart_term,  # stage-12 learns which concepts drive saves/follows
        "chart_type": chart_type, "seconds": seconds,
        "music": {"track": music_track, "licence": "self-synthesized / user-cleared (see assets/music/MUSIC_LICENSING.md)"},
        "watermark": vertical["handle"], "qc_passed": qc_passed, "qc_fails": qc_fails,
        "hashtags": cap["hashtags"],
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    # the approval hook: a watched flag file- write APPROVE or REJECT[:tag] into DECISION
    if qc_passed:
        (d / "APPROVAL_PENDING").write_text(
            "Write APPROVE or REJECT:<off-brand|weak-hook|wrong-lane|numbers-dull|factual-doubt> "
            "into a file named DECISION in this folder.\n"
            f"hook: {script.hook}\nreal: {result.vs_benchmark}\nclaimed: {result.claimed_result}\n"
            f"paper: {result.paper_ref}\n", encoding="utf-8")
    ledger.record_reel(slug, run_id, vertical["key"], result.paper_ref, script.hook_id,
                       chart_type, seconds, qc_passed, meta)
    return ReelPackage(slug=slug, vertical=vertical["key"], mp4_path=str(final_mp4),
                       thumbnail_path=thumb_path, caption_txt=str(caption_txt), meta=meta,
                       qc_passed=qc_passed)


def check_decisions() -> list[tuple[str, str, str | None]]:
    """Scan out/ for DECISION files, write them to the ledger, return [(slug, decision, tag)]."""
    acted = []
    for dec in OUT.glob("*/DECISION"):
        txt = dec.read_text(encoding="utf-8-sig").strip().upper()  # -sig: survive a PS5.1 BOM
        slug = dec.parent.name
        if txt.startswith("APPROVE"):
            ledger.set_approval(slug, "approved")
            acted.append((slug, "approved", None))
        elif txt.startswith("REJECT"):
            tag = txt.split(":", 1)[1].strip().lower() if ":" in txt else "untagged"
            ledger.set_approval(slug, "rejected", tag)
            acted.append((slug, "rejected", tag))
        (dec.parent / "APPROVAL_PENDING").unlink(missing_ok=True)
        dec.unlink()
    return acted


def post_reel(slug: str, vertical: dict) -> bool:
    """IG Graph API publish. Gated: ledger approval must be 'approved'; never auto-posts otherwise."""
    import os
    import sqlite3
    with ledger.conn() as c:
        row = c.execute("SELECT approval, posted FROM reels WHERE slug=?", (slug,)).fetchone()
    if not row or row[0] != "approved" or row[1]:
        return False
    key = vertical["key"].upper()
    user_id = os.environ.get(f"IG_{key}_USER_ID")
    token = os.environ.get(f"IG_{key}_ACCESS_TOKEN")
    if not (user_id and token):
        return False  # leave packaged for manual in-app posting (trending-audio route)
    # container -> publish flow; kept minimal, hardened in Slice C when accounts exist
    import requests
    d = OUT / slug
    caption = (d / "caption.txt").read_text(encoding="utf-8").split("\nALT TEXT")[0]
    try:
        r = requests.post(f"https://graph.facebook.com/v21.0/{user_id}/media",
                          data={"media_type": "REELS", "caption": caption,
                                "access_token": token}, timeout=30)
        cid = r.json().get("id")
        if not cid:
            return False
        r2 = requests.post(f"https://graph.facebook.com/v21.0/{user_id}/media_publish",
                           data={"creation_id": cid, "access_token": token}, timeout=30)
        ok = r2.status_code == 200
        if ok:
            media_id = r2.json().get("id", "")
            with ledger.conn() as c:
                row = c.execute("SELECT meta FROM reels WHERE slug=?", (slug,)).fetchone()
                meta = json.loads(row[0]) if row and row[0] else {}
                meta["ig_media_id"] = media_id  # stage 12 pulls insights by this id
                c.execute("UPDATE reels SET posted=1, meta=? WHERE slug=?",
                          (json.dumps(meta)[:20000], slug))
        return ok
    except Exception:
        return False
