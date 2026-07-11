"""Analytics dashboard (module 15)- the on-demand monitoring surface. Read-only.

Run: streamlit run dashboard.py   (pip install streamlit when the accounts go live)
Falls back to a terminal summary when streamlit isn't installed.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PERF = ROOT / "state" / "performance.json"


def _posts() -> list[dict]:
    return json.loads(PERF.read_text(encoding="utf-8")).get("posts", [])


def terminal_summary():
    posts = _posts()
    print(f"posts with numbers: {len(posts)}")
    if not posts:
        return
    by_hook = {}
    for p in posts:
        by_hook.setdefault(p.get("hook_id") or "?", []).append(p.get("saves", 0))
    print("hook-structure leaderboard (avg saves):")
    for h, vs in sorted(by_hook.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"  {h}: {sum(vs) / len(vs):.1f} ({len(vs)} reels)")


def streamlit_app():
    import pandas as pd
    import streamlit as st
    st.set_page_config(page_title="Reels Factory", layout="wide")
    st.title("Reels Factory- performance")
    posts = _posts()
    if not posts:
        st.info("No posted reels with numbers yet.")
        return
    df = pd.DataFrame(posts)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Follows per post")
        st.bar_chart(df.set_index("slug")["follows"])
        st.subheader("Hook-structure leaderboard")
        st.dataframe(df.groupby("hook_id")[["saves", "follows", "reach"]].mean().sort_values("saves", ascending=False))
    with c2:
        st.subheader("Per-reel funnel")
        st.dataframe(df[["slug", "vertical", "tone", "reach", "plays", "saves", "shares", "follows"]])
        st.subheader("Topic families")
        df["family"] = df["paper_ref"].fillna("?").str.extract(
            r"(momentum|reversion|vol|factor|calendar|pairs|crossover)", expand=False).fillna("other")
        st.bar_chart(df.groupby("family")["follows"].mean())


try:
    import streamlit  # noqa: F401
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

if __name__ == "__main__":
    terminal_summary()
elif _HAS_ST:
    streamlit_app()
