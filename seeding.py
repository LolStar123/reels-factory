"""--seed-from-quantihack: ingest the 50 pre-backtested, paper-cited strategies as the
launch buffer (PRD PRIOR ART #3- ~50 reels of material before the harvester runs once).
Routed per vertical, marked as seed so the 30-day dedup applies.
"""
from __future__ import annotations

import csv
from pathlib import Path

import ledger
from theme import ROOT

CSV = ROOT / "seed" / "quantihack_alt_data_50_results.csv"

# family -> vertical routing (vol-surface/microstructure -> quant lane; calendar/behavioural stay accessible)
QUANT_FAMILIES = {"volatility", "vol", "microstructure", "cross-asset"}


def seed() -> int:
    if not CSV.exists():
        print(f"missing {CSV}")
        return 1
    n = 0
    with open(CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("strategy") or row.get("name") or f"seed-{n}"
            fam = (row.get("family") or row.get("category") or "").lower()
            vertical = "wannabe_quant" if any(q in fam for q in QUANT_FAMILIES) else "high_finance"
            pid = f"seed:{name[:60]}"
            ledger.add_paper(pid, name, "quantihack-seed", 0.9, status="seed")
            with ledger.conn() as c:
                c.execute("INSERT OR REPLACE INTO reels (slug, run_id, vertical, paper_ref, "
                          "hook_id, chart_type, seconds, qc_passed, approval, posted, created, meta) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),?)",
                          (f"seedbank_{n:02d}_{name[:40].replace(' ', '-').lower()}", "seed-run",
                           vertical, name, "", "equity_race", 0, 0, "seed-material", 0,
                           str(dict(row))[:5000]))
            n += 1
    print(f"seeded {n} pre-backtested strategies into the ledger "
          f"(status=seed-material; build_reel renders them on demand via --paper seed:<name>)")
    print("SEEDING.md documents the flow; the opening 9-grid comes from the top of this bank.")
    return 0
