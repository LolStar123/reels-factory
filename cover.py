"""Thumbnail/cover-frame generator (module 17)- the IG grid is a shop window.

assemble.make_thumbnail already renders the default cover (finished curve + hook text);
this module adds grid-consistency variants for A/B (module 16) once accounts are live.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from theme import ROOT, colours, font_path


def variant_covers(base_cover: Path, hook: str, outdir: Path, n: int = 2) -> list[Path]:
    """Generate n cover variants: (a) hook-top, (b) hook-boxed- tagged for the experiment log."""
    outs = []
    c = colours()
    for i, style in enumerate(["top", "boxed"][:n]):
        img = Image.open(base_cover).convert("RGB")
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(str(font_path("headline_heavy")), 60)
        lines = textwrap.wrap(hook, width=26)
        if style == "boxed":
            pad, lh = 24, 72
            box_h = len(lines) * lh + 2 * pad
            d.rectangle([60, 200, img.width - 60, 200 + box_h], fill=c["bg"])
            y = 200 + pad
        else:
            y = 160
        for line in lines:
            tw = d.textlength(line, font=f)
            d.text(((img.width - tw) / 2, y), line, font=f,
                   fill=c["accent"] if style == "boxed" else "#FFFFFF")
            y += 72
        p = outdir / f"cover_var_{style}.png"
        img.save(p)
        outs.append(p)
    return outs
