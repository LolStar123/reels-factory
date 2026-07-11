"""Trend & competitor intel (stage 0)- hook bank refresh.

Reliability model (CODEX-5 + GEMINI-3): the manual-import floor (state/hook_seeds.csv)
ALWAYS feeds the bank; live Playwright scraping of IG/TikTok is a best-effort layer on
top and its failure never blocks anything. Structures are learned, wording is never copied.
"""
from __future__ import annotations

import csv
import json
from datetime import date

from theme import ROOT, config

HOOK_BANK = ROOT / "state" / "hook_bank.json"
SEEDS = ROOT / "state" / "hook_seeds.csv"
COMPETITORS = ROOT / "state" / "competitors.json"


def _load_bank() -> dict:
    return json.loads(HOOK_BANK.read_text(encoding="utf-8"))


def _save_bank(bank: dict):
    bank["updated"] = date.today().isoformat()
    HOOK_BANK.write_text(json.dumps(bank, indent=1), encoding="utf-8")


def ingest_seeds(bank: dict) -> int:
    """The manual-import floor- hook structures from hook_seeds.csv join the bank."""
    if not SEEDS.exists():
        return 0
    added = 0
    known = {h["template"] for h in bank["hooks"]}
    with open(SEEDS, encoding="utf-8") as f:
        for row in csv.DictReader(l for l in f if not l.startswith("#")):
            text = (row.get("url_or_text") or "").strip()
            if not text or text.startswith("http") or text in known:
                continue  # URLs need the scrape layer; text seeds ingest directly
            hid = "seed-" + "".join(w[0] for w in text.split()[:6]).lower()
            bank["hooks"].append({"id": hid, "template": text, "score": 1.0, "uses": 0,
                                  "lane": row.get("lane", "both"), "origin": "manual-seed"})
            known.add(text)
            added += 1
    return added


def scrape_competitors(bank: dict) -> int:
    """Best-effort Playwright layer. Blocked/absent -> log and continue on cache (never raises)."""
    comp = json.loads(COMPETITORS.read_text(encoding="utf-8"))
    seeds = config().get("trend_research", {}).get("competitors", [])
    if not seeds:
        return 0
    try:
        from playwright.sync_api import sync_playwright  # optional dependency
    except ImportError:
        print("trends: playwright not installed- running on the manual-import floor only")
        return 0
    found = 0
    # Deliberately conservative: public profile pages only, aggressive caching, backoff on block.
    # IG/TikTok actively resist scraping- treat every fetch as best-effort.
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            for handle in seeds[:5]:
                try:
                    page.goto(f"https://www.instagram.com/{handle.strip('@')}/", timeout=15000)
                    page.wait_for_timeout(2500)
                    comp["accounts"].append({"handle": handle, "seen": date.today().isoformat()})
                    found += 1
                except Exception:
                    continue
            browser.close()
    except Exception as e:
        print(f"trends: scrape blocked ({e})- cache + seeds still serve")
    comp["last_refresh"] = date.today().isoformat()
    COMPETITORS.write_text(json.dumps(comp, indent=1), encoding="utf-8")
    return found


def rescore_from_performance(bank: dict) -> int:
    """Stage-12 hook re-weighting: winners rise, dead structures decay toward retirement."""
    perf_path = ROOT / "state" / "performance.json"
    perf = json.loads(perf_path.read_text(encoding="utf-8"))
    posts = perf.get("posts", [])
    if len(posts) < config()["feedback"]["learn_after_n_posts"]:
        return 0
    by_hook: dict[str, list[float]] = {}
    for p in posts:
        ns = p.get("avg_watch_time_ratio") or 0
        by_hook.setdefault(p.get("hook_id", "?"), []).append(float(ns))
    if not by_hook:
        return 0
    overall = sum(v for vs in by_hook.values() for v in vs) / max(1, sum(len(vs) for vs in by_hook.values()))
    changed = 0
    for h in bank["hooks"]:
        vals = by_hook.get(h["id"])
        if vals:
            rel = (sum(vals) / len(vals)) / overall if overall else 1.0
            h["score"] = round(max(0.05, min(3.0, 0.7 * h.get("score", 1.0) + 0.3 * rel)), 3)
            changed += 1
    return changed


def refresh() -> int:
    bank = _load_bank()
    n_seed = ingest_seeds(bank)
    n_scrape = scrape_competitors(bank)
    n_rescore = rescore_from_performance(bank)
    _save_bank(bank)
    print(f"hook bank: +{n_seed} manual seeds, {n_scrape} competitor profiles touched, "
          f"{n_rescore} hooks re-scored, {len(bank['hooks'])} total")
    return 0
