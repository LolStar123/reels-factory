"""THE layout system- single source of truth for where anything may draw.

The 1080x1920 frame is partitioned into EXCLUSIVE horizontal bands. Every renderer
(charts, cards, ASS captions, watermark overlay, thumbnails) takes its coordinates
from here and clamps its content inside its band- overlap is impossible by
construction, not by coordinate luck. Never place text with a raw pixel number;
add or resize a zone here instead.
"""
from __future__ import annotations

from PIL import ImageDraw, ImageFont

FRAME_W, FRAME_H = 1080, 1920

# top -> bottom, contiguous, non-overlapping (px)
ZONES = {
    "top_safe":  (0,    220),   # IG UI- nothing renders here
    "title":     (220,  480),   # chart title/subtitle · card headline overflow
    "content":   (480,  1120),  # chart axes · card body text
    "stats":     (1120, 1330),  # final value + stat card · as-of line · card disclaimer
    "captions":  (1330, 1500),  # karaoke ASS captions ONLY
    "watermark": (1500, 1600),  # drifting watermark ONLY
    "bottom_safe": (1600, 1920),  # IG UI- nothing renders here
}

SIDE_MARGIN = 60  # px each side for any text block


def zone(name: str) -> tuple[int, int]:
    return ZONES[name]


def zone_h(name: str) -> int:
    a, b = ZONES[name]
    return b - a


def fig_y(px_y: float) -> float:
    """Pixel y (from top) -> matplotlib figure fraction (from bottom)."""
    return 1.0 - px_y / FRAME_H


def fig_rect(top_zone_px: int, bottom_zone_px: int, x0: int = 108, x1: int = 1015) -> list[float]:
    """Matplotlib add_axes rect [left, bottom, width, height] spanning the given px band."""
    return [x0 / FRAME_W, fig_y(bottom_zone_px), (x1 - x0) / FRAME_W,
            (bottom_zone_px - top_zone_px) / FRAME_H]


def ass_margin_v() -> int:
    """ASS MarginV (distance of the caption baseline band from frame bottom)."""
    return FRAME_H - ZONES["captions"][1]


def ass_max_font(lines: int = 2) -> int:
    """Caption font size such that `lines` lines + outline stay inside the captions band."""
    return int(zone_h("captions") / (lines * 1.45))


def watermark_y_expr(wm_h_px: int = 70) -> str:
    """ffmpeg overlay y- vertically centred in the watermark band (constant, drift is x-only)."""
    top, bot = ZONES["watermark"]
    return str(top + max(0, (bot - top - wm_h_px) // 2))


# ── PIL text fitting: measured wrap + shrink-to-fit, clamped to a band ─────────
def wrap_measured(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                  max_w: int) -> list[str]:
    """Wrap by MEASURED pixel width (never by character count)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text_block(draw: ImageDraw.ImageDraw, text: str, font_path: str, start_size: int,
                   band: tuple[int, int], line_gap: float = 1.25,
                   min_size: int = 28) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Largest font <= start_size whose wrapped block fits the band (w and h).

    Returns (font, lines, y_top_for_vertical_centering). Shrinks until it fits-
    a text block can NEVER overflow its zone.
    """
    band_top, band_bot = band
    band_h = band_bot - band_top
    max_w = FRAME_W - 2 * SIDE_MARGIN
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_measured(draw, text, font, max_w)
        block_h = int(len(lines) * size * line_gap)
        if block_h <= band_h:
            y0 = band_top + (band_h - block_h) // 2
            return font, lines, y0
        size = int(size * 0.88)
    font = ImageFont.truetype(font_path, min_size)
    lines = wrap_measured(draw, text, font, max_w)
    return font, lines, band_top


def draw_block(draw: ImageDraw.ImageDraw, text: str, font_path: str, start_size: int,
               band_name: str, colour: str, line_gap: float = 1.25) -> int:
    """Draw a centred, fitted text block inside a named zone. Returns the block's bottom y."""
    band = zone(band_name)
    font, lines, y = fit_text_block(draw, text, font_path, start_size, band, line_gap)
    size = font.size
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((FRAME_W - tw) / 2, y), line, font=font, fill=colour)
        y += int(size * line_gap)
    return y
