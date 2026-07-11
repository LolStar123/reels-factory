"""SQLite job/state ledger (CODEX-8)- papers / runs / reels / approvals / failures / retries.

Transactional state for resumability + buffer management. The state/*.json files stay
as inspectable config-shaped state; this is the machine ledger.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from theme import ROOT

DB = ROOT / "state" / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, title TEXT, source TEXT,
  testability REAL, status TEXT, added TEXT);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started TEXT, kind TEXT,
  status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS reels (slug TEXT PRIMARY KEY, run_id TEXT, vertical TEXT,
  paper_ref TEXT, hook_id TEXT, chart_type TEXT, seconds REAL, qc_passed INTEGER,
  approval TEXT DEFAULT 'pending', reject_tag TEXT, posted INTEGER DEFAULT 0,
  created TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS failures (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
  stage TEXT, detail TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS retries (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
  stage TEXT, attempt INTEGER, at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.executescript(_SCHEMA)
    return c


def start_run(run_id: str, kind: str):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                  (run_id, _now(), kind, "running", ""))


def finish_run(run_id: str, status: str, detail: str = ""):
    with conn() as c:
        c.execute("UPDATE runs SET status=?, detail=? WHERE run_id=?", (status, detail, run_id))


def log_failure(run_id: str, stage: str, detail: str):
    with conn() as c:
        c.execute("INSERT INTO failures (run_id, stage, detail, at) VALUES (?,?,?,?)",
                  (run_id, stage, detail[:2000], _now()))


def record_reel(slug: str, run_id: str, vertical: str, paper_ref: str, hook_id: str,
                chart_type: str, seconds: float, qc_passed: bool, meta: dict):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO reels (slug, run_id, vertical, paper_ref, hook_id, "
                  "chart_type, seconds, qc_passed, created, meta) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (slug, run_id, vertical, paper_ref, hook_id, chart_type, seconds,
                   int(qc_passed), _now(), json.dumps(meta)[:20000]))


def set_approval(slug: str, decision: str, reject_tag: str | None = None):
    with conn() as c:
        c.execute("UPDATE reels SET approval=?, reject_tag=? WHERE slug=?",
                  (decision, reject_tag, slug))


def buffer_count(vertical: str | None = None) -> int:
    with conn() as c:
        q = "SELECT COUNT(*) FROM reels WHERE approval='approved' AND posted=0"
        if vertical:
            return c.execute(q + " AND vertical=?", (vertical,)).fetchone()[0]
        return c.execute(q).fetchone()[0]


def add_paper(pid: str, title: str, source: str, testability: float, status: str = "new"):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO papers VALUES (?,?,?,?,?,?)",
                  (pid, title, source, testability, status, _now()))
