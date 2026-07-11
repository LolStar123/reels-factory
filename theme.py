"""Brand theme: config loader, font registration, colours, ffmpeg resolution.

Fonts fail LOUDLY if missing (PRD edge case)- never fall back to system fonts.
"""
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"

FONT_FILES = {
    "headline": "Montserrat-SemiBold.ttf",
    "headline_heavy": "Montserrat-ExtraBold.ttf",
    "body": "Inter-Regular.ttf",
    "body_medium": "Inter-Medium.ttf",
    "mono": "JetBrainsMono-Regular.ttf",
    "mono_bold": "JetBrainsMono-Bold.ttf",
}
FONT_FAMILIES = {  # matplotlib registers under the TYPOGRAPHIC family (name id 16) when present
    "headline": "Montserrat",        # pair with fontweight="semibold" / "heavy"
    "headline_heavy": "Montserrat",
    "body": "Inter",
    "mono": "JetBrains Mono",
}

_cfg = None


def config() -> dict:
    global _cfg
    if _cfg is None:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)
    return _cfg


def colours() -> dict:
    return config()["brand"]["colours"]


def font_path(key: str) -> Path:
    p = ROOT / "assets" / "fonts" / FONT_FILES[key]
    if not p.exists():
        sys.exit(f"FATAL: bundled font missing: {p}\nDrop the .ttf in assets/fonts/ - system-font fallback is forbidden.")
    return p


def register_matplotlib_fonts():
    """Register every bundled TTF with matplotlib. Call before any figure is made."""
    import matplotlib.font_manager as fm
    for key in FONT_FILES:
        fm.fontManager.addfont(str(font_path(key)))


def video_params() -> dict:
    v = config()["video"]
    w, h = (int(x) for x in v["resolution"].split("x"))
    return {"w": w, "h": h, "fps": int(v["fps"]), "target_seconds": v["target_seconds"],
            "chart_draw_seconds": v["chart_draw_seconds"], "safe_top": v["safe_area"]["top_px"],
            "safe_bottom": v["safe_area"]["bottom_px"]}


def ffmpeg_exe() -> str:
    """ffmpeg on PATH, else the winget absolute path, else imageio-ffmpeg's bundled binary."""
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / (
        r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")
    if winget.exists():
        return str(winget)
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def vertical(key: str) -> dict:
    for v in config()["verticals"]:
        if v["key"] == key:
            return v
    raise KeyError(f"unknown vertical {key!r}")
