"""Audio bed- pick a cleared track deterministically, loop/trim, duck under VO, -14 LUFS.

If assets/music/ is empty: VO-only, log it, never crash, never fetch an unlicensed track.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from theme import ROOT, config, ffmpeg_exe

MUSIC_DIR = ROOT / "assets" / "music"


def pick_bed(slug: str) -> Path | None:
    tracks = sorted(list(MUSIC_DIR.glob("*.wav")) + list(MUSIC_DIR.glob("*.mp3")))
    if not tracks:
        return None
    idx = int(hashlib.sha1(slug.encode()).hexdigest(), 16) % len(tracks)
    return tracks[idx]


def mix_audio(vo_wav: Path | None, slug: str, duration: float, workdir: Path) -> Path | None:
    """Returns the final mixed stereo track, or None (silent reel is assembler's problem)."""
    cfg = config()["music"]
    duck_db = int(cfg["duck_under_voice_db"])
    bed = pick_bed(slug)
    out = workdir / "mix.wav"
    ff = ffmpeg_exe()

    if bed is None and vo_wav is None:
        return None
    if bed is None:
        # VO only, normalised
        subprocess.run([ff, "-y", "-i", str(vo_wav), "-af", "loudnorm=I=-14:TP=-1.5",
                        "-t", f"{duration}", str(out)], capture_output=True, check=True)
        return out
    if vo_wav is None:
        subprocess.run([ff, "-y", "-stream_loop", "-1", "-i", str(bed),
                        "-af", f"volume={duck_db}dB,afade=t=in:d=0.5,afade=t=out:st={duration - 0.8}:d=0.8,loudnorm=I=-16:TP=-1.5",
                        "-t", f"{duration}", str(out)], capture_output=True, check=True)
        return out

    # bed looped + sidechain-ducked under the VO, fades, loudness-normalised to ~-14 LUFS
    filt = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{duration},afade=t=in:d=0.5,"
            f"afade=t=out:st={max(0.0, duration - 0.8)}:d=0.8[bed];"
            f"[0:a]apad=whole_dur={duration}[vo];"
            f"[bed][vo]sidechaincompress=threshold=0.02:ratio=8:attack=50:release=400:makeup=1[duck];"
            f"[vo][duck]amix=inputs=2:duration=first:weights=1 {10 ** (duck_db / 20):.3f}[premix];"
            f"[premix]loudnorm=I=-14:TP=-1.5[out]")
    r = subprocess.run([ff, "-y", "-i", str(vo_wav), "-i", str(bed),
                        "-filter_complex", filt, "-map", "[out]", "-ac", "2",
                        "-t", f"{duration}", str(out)], capture_output=True)
    if r.returncode != 0:
        # simpler fallback mix: static bed volume under VO
        filt = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{duration},volume={duck_db}dB[bed];"
                f"[0:a]apad=whole_dur={duration}[vo];[vo][bed]amix=inputs=2:duration=first,"
                f"loudnorm=I=-14:TP=-1.5[out]")
        subprocess.run([ff, "-y", "-i", str(vo_wav), "-i", str(bed),
                        "-filter_complex", filt, "-map", "[out]", "-ac", "2",
                        "-t", f"{duration}", str(out)], capture_output=True, check=True)
    return out
