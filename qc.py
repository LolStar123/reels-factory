"""QC gate- hard asserts before anything is packaged. Fail -> log + never post a broken/dishonest reel.

The honesty gate: on-screen numbers (overlays.json, CODEX-9) must equal BacktestResult- by
construction, no OCR. Absolute- it wins over any performance nudge.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from compliance import has_disclaimer, lint_text
from contracts import BacktestResult, Script
from theme import ffmpeg_exe, video_params


def _probe(mp4: Path) -> dict:
    ff = Path(ffmpeg_exe())
    ffprobe = str(ff.with_name(ff.name.replace("ffmpeg", "ffprobe"))) if ff.is_absolute() else "ffprobe"
    r = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams",
                        "-show_format", str(mp4)], capture_output=True, text=True)
    return json.loads(r.stdout)


def _frame_at(mp4: Path, spec: str, out: Path):
    ff = ffmpeg_exe()
    if spec == "first":
        subprocess.run([ff, "-y", "-i", str(mp4), "-frames:v", "1", str(out)],
                       capture_output=True, check=True)
        return
    # last frame: seek by measured duration (-sseof is unreliable after a -c:v copy remux)
    info = _probe(mp4)
    dur = float(info["format"]["duration"])
    for back in (0.2, 0.6, 1.2):
        subprocess.run([ff, "-y", "-ss", f"{max(0.0, dur - back):.3f}", "-i", str(mp4),
                        "-update", "1", "-frames:v", "1", str(out)], capture_output=True)
        if out.exists():
            return
    raise FileNotFoundError(f"could not extract last frame of {mp4}")


def zone_discipline(workdir: Path) -> list[str]:
    """Pixel tripwire for the layout system: the caption + watermark bands (and top_safe)
    must be PURE BACKGROUND in every card and in the chart segment- those bands belong to
    the ASS burner and the watermark overlay alone. Any renderer that leaks into them
    fails the reel here, permanently, no matter who edits what later.
    """
    from PIL import Image
    from layout import zone
    from theme import colours
    bg = colours()["bg"]
    bg_rgb = np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    fails = []
    targets = sorted(workdir.glob("card_*.png"))
    chart_mp4 = workdir / "chart.mp4"
    if chart_mp4.exists():
        last = workdir / "_qc_chart_last.png"
        _frame_at(chart_mp4, "last", last)
        targets.append(last)
    for p in targets:
        arr = np.asarray(Image.open(p).convert("RGB"), dtype=float)
        for band in ("top_safe", "captions", "watermark"):
            a, b = zone(band)
            if np.abs(arr[a:b] - bg_rgb).mean() > 4.0:
                fails.append(f"ZONE: {p.name} draws into the exclusive '{band}' band")
    (workdir / "_qc_chart_last.png").unlink(missing_ok=True)
    return fails


def run_qc(mp4: Path, overlays_path: Path, result: BacktestResult, script: Script,
           workdir: Path) -> tuple[bool, list[str]]:
    fails: list[str] = []
    vp = video_params()
    fails += zone_discipline(workdir)

    info = _probe(mp4)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    size_mb = int(info["format"]["size"]) / 1e6

    if not (20 <= dur <= 45):
        fails.append(f"duration {dur:.1f}s outside [20,45]")
    if v is None or int(v["width"]) != vp["w"] or int(v["height"]) != vp["h"]:
        fails.append(f"resolution {v and (v['width'], v['height'])} != {vp['w']}x{vp['h']}")
    if v is not None:
        num, den = v["avg_frame_rate"].split("/")
        if abs(float(num) / float(den) - vp["fps"]) > 0.6:
            fails.append(f"fps {float(num) / float(den):.1f} != {vp['fps']}")
    if a is None:
        fails.append("no audio stream")
    if size_mb > 100:
        fails.append(f"file {size_mb:.0f}MB > 100MB")

    # HONESTY GATE: overlays == backtest output
    ov = json.loads(Path(overlays_path).read_text(encoding="utf-8"))
    m = result.metrics
    checks = [("final_value", round(m["final_value"])), ("benchmark_final", round(m["benchmark_final"])),
              ("cagr_pct", round(m["cagr"] * 100, 2)), ("sharpe", round(m["sharpe"], 2)),
              ("mdd_pct", round(m["mdd"] * 100, 2))]
    for key, want in checks:
        if key in ov and abs(float(ov[key]) - float(want)) > 0.011:
            fails.append(f"HONESTY: on-screen {key}={ov[key]} != backtest {want}")

    # banned-phrase lint + disclaimer
    ok, why = lint_text(script.hook, *script.beats, script.cta, script.caption)
    if not ok:
        fails.append(f"COMPLIANCE: {why}")
    if not has_disclaimer(script.caption):
        fails.append("COMPLIANCE: caption missing the disclaimer")
    if script.cites_paper and script.cites_paper not in script.caption:
        fails.append("caption missing the paper citation")

    # black-frame + loop-seam checks
    try:
        f0, fN = workdir / "_qc_first.png", workdir / "_qc_last.png"
        _frame_at(mp4, "first", f0)
        _frame_at(mp4, "last", fN)
        from PIL import Image
        a0 = np.asarray(Image.open(f0).convert("L"), dtype=float)
        aN = np.asarray(Image.open(fN).convert("L"), dtype=float)
        if a0.mean() < 2:
            fails.append("first frame is black")
        diff = np.abs(a0 - aN).mean()
        if diff > 24:
            fails.append(f"loop seam not clean (first/last frame diff {diff:.0f})")
        f0.unlink(); fN.unlink()
    except Exception as e:
        fails.append(f"frame check errored: {e}")

    return (len(fails) == 0), fails
