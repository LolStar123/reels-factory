"""Compliance- deliberately minimal by design: a banned-phrase lint + the disclaimer check.
A lint, not a scanner (CODEX-6). One literal match fails the reel.
"""
from __future__ import annotations

from theme import config


def lint_text(*texts: str) -> tuple[bool, str]:
    banned = [p.lower() for p in config()["compliance"]["banned_phrases"]]
    blob = " ".join(t.lower() for t in texts if t)
    for phrase in banned:
        if phrase in blob:
            return False, f"banned phrase present: {phrase!r}"
    return True, "ok"


def has_disclaimer(caption: str) -> bool:
    return "not financial advice" in caption.lower() or "educational only" in caption.lower()
