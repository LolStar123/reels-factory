"""Community manager (module 14)- comments & DMs, APPROVAL-GATED in v1.

Drafts replies in brand voice; nothing posts publicly without a relayed OK. Auto-actions
are limited to nothing in v1 (hearts/hide-spam unlock later by flag). Mines questions
for future reel ideas -> the backlog.
"""
from __future__ import annotations

import json
import os
from datetime import date

from theme import ROOT, config

DRAFTS = ROOT / "state" / "community_drafts.json"
BACKLOG = ROOT / "state" / "audience_backlog.json"

FAQ = {
    "advice": "Educational only- I report backtests, never advice. Capital at risk.",
    "broker": "Data is Interactive Brokers first, free sources as fallback- flagged on the chart when so.",
    "code": "The engine is a walk-forward backtester with costs + slippage; every reel's numbers come straight from it.",
    "paper": "Full citation is in the caption- title + year. Read the original, it's usually worth it.",
}


def fetch_comments(vertical: dict, limit: int = 25) -> list[dict]:
    """IG Graph API comments on recent media. Empty when no token (accounts not live)."""
    key = vertical["key"].upper()
    token = os.environ.get(f"IG_{key}_ACCESS_TOKEN")
    user_id = os.environ.get(f"IG_{key}_USER_ID")
    if not (token and user_id):
        return []
    import requests
    try:
        media = requests.get(f"https://graph.facebook.com/v21.0/{user_id}/media",
                             params={"fields": "id,caption", "limit": 10,
                                     "access_token": token}, timeout=20).json().get("data", [])
        out = []
        for m in media:
            cs = requests.get(f"https://graph.facebook.com/v21.0/{m['id']}/comments",
                              params={"fields": "id,text,username", "limit": limit,
                                      "access_token": token}, timeout=20).json().get("data", [])
            out.extend({"media_id": m["id"], **c} for c in cs)
        return out
    except Exception:
        return []


def draft_replies(vertical: dict) -> int:
    """FAQ-match + flag; drafts land in community_drafts.json for the relay/approval loop."""
    comments = fetch_comments(vertical)
    drafts = json.loads(DRAFTS.read_text(encoding="utf-8")) if DRAFTS.exists() else \
        {"schema_version": 1, "drafts": []}
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8")) if BACKLOG.exists() else \
        {"schema_version": 1, "ideas": []}
    n = 0
    for cm in comments:
        text = cm.get("text", "").lower()
        reply = next((r for k, r in FAQ.items() if k in text), None)
        if "?" in text and not reply:
            backlog["ideas"].append({"from": cm.get("username"), "q": cm.get("text", "")[:300],
                                     "date": date.today().isoformat()})
        if reply:
            drafts["drafts"].append({"comment_id": cm["id"], "user": cm.get("username"),
                                     "their": cm.get("text", "")[:300], "draft": reply,
                                     "status": "pending-approval", "vertical": vertical["key"]})
            n += 1
    DRAFTS.write_text(json.dumps(drafts, indent=1), encoding="utf-8")
    BACKLOG.write_text(json.dumps(backlog, indent=1), encoding="utf-8")
    return n
