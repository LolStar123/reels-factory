"""External reviewer- an independent quality pass on a FINISHED reel, distinct from qc.py.

qc.py asserts the contract (honesty, zones, format); this module judges the reel the way
a video editor would, using real analysis tooling:
  - PySceneDetect (github.com/Breakthrough/PySceneDetect)- cut structure + pacing
  - ffmpeg loudnorm- measured integrated loudness vs the -14 LUFS reels target
  - ffmpeg freezedetect / blackdetect- dead air on screen
  - silencedetect on the audio- VO gaps that drag
  - frame-level contrast/brightness stats- legibility

Run: python run.py --review <slug>   (or --review latest). Writes out/<slug>/review.md
with a score /10 and concrete fixes; exit 1 below threshold so batch jobs can gate on it.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from theme import ROOT, ffmpeg_exe

TARGET_LUFS = -14.0
LUFS_TOL = 2.0
MAX_STATIC_SHOT = 14.0   # a single visual holding longer than this drags
MAX_SILENCE_MID = 2.6    # silence gap (s) inside the VO body that feels dead


def _ff(args: list[str]) -> str:
    r = subprocess.run([ffmpeg_exe(), *args], capture_output=True, text=True)
    return r.stderr  # ffmpeg reports analysis on stderr


def measure_loudness(mp4: Path) -> dict | None:
    err = _ff(["-i", str(mp4), "-af", "loudnorm=I=-14:TP=-1.5:print_format=json",
               "-f", "null", "-"])
    m = re.search(r"\{[^{}]+\}", err[err.rfind("Parsed_loudnorm"):] or "")
    if not m:
        return None
    d = json.loads(m.group(0))
    return {"input_i": float(d["input_i"]), "input_tp": float(d["input_tp"]),
            "input_lra": float(d["input_lra"])}


def detect_scenes(mp4: Path) -> list[float]:
    """Shot lengths in seconds via PySceneDetect ContentDetector."""
    from scenedetect import ContentDetector, detect
    # low threshold: our cuts are text swaps on a dark ground- most pixels don't change
    scenes = detect(str(mp4), ContentDetector(threshold=8.0, min_scene_len=15))
    return [(e - s).get_seconds() for s, e in scenes]


def detect_freezes(mp4: Path) -> list[tuple[float, float]]:
    err = _ff(["-i", str(mp4), "-vf", "freezedetect=n=-60dB:d=4", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def detect_silences(mp4: Path) -> list[tuple[float, float]]:
    err = _ff(["-i", str(mp4), "-af", "silencedetect=noise=-38dB:d=1.2", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    durs = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err)]
    return list(zip(starts, durs))


def frame_stats(mp4: Path, at: float) -> dict | None:
    from PIL import Image
    tmp = ROOT / "state" / "work" / "_rev_frame.png"
    subprocess.run([ffmpeg_exe(), "-y", "-ss", str(max(0, at)), "-i", str(mp4), "-update", "1",
                    "-frames:v", "1", str(tmp)], capture_output=True)
    if not tmp.exists():
        return None
    arr = np.asarray(Image.open(tmp).convert("L"), dtype=float)
    tmp.unlink(missing_ok=True)
    return {"mean": float(arr.mean()), "contrast": float(arr.std())}


def review(slug: str) -> int:
    d = ROOT / "out" / slug
    mp4 = next(d.glob("*.mp4"), None)
    if mp4 is None:
        print(f"no mp4 in out/{slug}")
        return 2
    findings, score = [], 10.0

    dur = float(json.loads(subprocess.run(
        [str(Path(ffmpeg_exe()).with_name(Path(ffmpeg_exe()).name.replace("ffmpeg", "ffprobe"))),
         "-v", "quiet", "-print_format", "json", "-show_format", str(mp4)],
        capture_output=True, text=True).stdout)["format"]["duration"])

    loud = measure_loudness(mp4)
    if loud:
        if abs(loud["input_i"] - TARGET_LUFS) > LUFS_TOL:
            findings.append(f"loudness {loud['input_i']:.1f} LUFS vs target {TARGET_LUFS} "
                            f"(fix: final-mix loudnorm pass)")
            score -= 1.5
        if loud["input_tp"] > -1.0:
            findings.append(f"true peak {loud['input_tp']:.1f} dBTP > -1.0 (risk of clipping on IG transcode)")
            score -= 1.0
    else:
        findings.append("could not measure loudness")
        score -= 0.5

    # advisory only: ContentDetector under-detects cuts on dark minimal frames, so shot
    # structure informs but never scores; true static is what freezedetect (scored) catches
    shots = detect_scenes(mp4)
    long_shots = [s for s in shots if s > MAX_STATIC_SHOT]
    if long_shots:
        findings.append(f"(advisory) longest detected shot {max(long_shots):.1f}s- "
                        "check pacing by eye; dark cuts often evade the detector")

    freezes = [f for f in detect_freezes(mp4) if f[0] > 1.0]
    if freezes:
        findings.append(f"frozen frame(s) at {[round(f[0], 1) for f in freezes]} (>4s static)")
        score -= 1.0

    sil = [(s, du) for s, du in detect_silences(mp4)
           if 1.0 < s < dur - 3.0 and du > MAX_SILENCE_MID]
    if sil:
        findings.append(f"dead audio gaps mid-reel: {[(round(s, 1), round(du, 1)) for s, du in sil]}"
                        " (tighten the schedule or lift the bed)")
        score -= min(2.0, len(sil) * 0.8)

    for label, at in (("hook", 1.0), ("chart", min(dur / 2, 12)), ("cta", dur - 2)):
        st = frame_stats(mp4, at)
        if st is None:
            continue
        if st["contrast"] < 12:
            findings.append(f"{label} frame at {at:.0f}s is low-contrast ({st['contrast']:.0f})- text may not pop")
            score -= 0.5

    score = max(0.0, round(score, 1))
    lines = [f"# Review- {slug}", f"score: **{score}/10**  ·  duration {dur:.1f}s",
             f"loudness: {loud}" if loud else "loudness: unmeasured",
             f"shots: {[round(s, 1) for s in shots]}", ""]
    lines += [f"- {f}" for f in findings] or ["- clean: no findings"]
    (d / "review.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if score >= 7.0 else 1


def latest_slug() -> str | None:
    dirs = [p for p in (ROOT / "out").iterdir() if p.is_dir() and list(p.glob("*.mp4"))]
    return max(dirs, key=lambda p: p.stat().st_mtime).name if dirs else None
