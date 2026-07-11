"""Assembly- text cards + chart segment + VO + ducked bed + karaoke ASS captions
+ drifting watermark + seamless loop (last frame flows into first, NICHE 2).
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from contracts import Insight, Script
from theme import ROOT, colours, config, ffmpeg_exe, font_path, video_params

LOGO_DIR = ROOT / "assets" / "logo"


# ── PIL text cards ───────────────────────────────────────────────────────────
def _font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(key)), size)


def _card(blocks: list[tuple[str, str, int, str]], out: Path, sub: str = ""):
    """blocks: [(text, font_key, start_size, colour_hex)] drawn inside the CONTENT zone,
    measured-wrapped and shrunk-to-fit (layout.py)- card text can never leave its band.
    `sub` (disclaimer) renders in the STATS zone; captions + watermark own their own bands.
    """
    from layout import ZONES, draw_block, fit_text_block, zone
    c = colours()
    img = Image.new("RGB", (layout_w(), layout_h()), c["bg"])
    d = ImageDraw.Draw(img)
    top, bot = zone("content")
    n = len(blocks)
    # split the content band evenly across blocks, in order
    for i, (text, fkey, size, col) in enumerate(blocks):
        band = (top + (bot - top) * i // n, top + (bot - top) * (i + 1) // n)
        font, lines, y = fit_text_block(d, text, str(font_path(fkey)), size, band)
        for line in lines:
            tw = d.textlength(line, font=font)
            d.text(((img.width - tw) / 2, y), line, font=font, fill=col)
            y += int(font.size * 1.25)
    if sub:
        draw_block(d, sub, str(font_path("body")), 26, "stats", "#6A7079")
    img.save(out)


def layout_w() -> int:
    from layout import FRAME_W
    return FRAME_W


def layout_h() -> int:
    from layout import FRAME_H
    return FRAME_H


def build_cards(script: Script, insight: Insight, workdir: Path, vertical: dict) -> dict[str, Path]:
    c = colours()
    disclaimer = config()["compliance"]["hard_disclaimer"]
    cards = {}
    hook_p = workdir / "card_hook.png"
    if script.hook_number:
        # 3-second rule: the money number IS the visual hook- huge, colour-coded, instant
        num_col = c["negative"] if script.hook_number.startswith("-") else \
            (c["positive"] if script.hook_number.startswith("+") else c["accent"])
        _card([(script.hook_number, "mono_bold", 150, num_col),
               (script.hook, "headline_heavy", 62, c["text"])], hook_p,
              sub=disclaimer if insight.risk_flag else "")
    else:
        _card([(script.hook, "headline_heavy", 76, c["text"])], hook_p,
              sub=disclaimer if insight.risk_flag else "")
    cards["hook"] = hook_p
    for i, beat in enumerate(script.beats[1:], start=1):  # beat 0 plays over the chart
        p = workdir / f"card_beat{i}.png"
        _card([(beat, "headline", 58, c["text"])], p)
        cards[f"beat{i}"] = p
    cta_p = workdir / "card_cta.png"
    _card([(vertical["display_name"], "headline_heavy", 84, c["accent"]),
           (script.cta, "headline", 50, c["text"])], cta_p, sub=disclaimer)
    cards["cta"] = cta_p
    return cards


# ── watermark ────────────────────────────────────────────────────────────────
def build_watermark(vertical: dict) -> Path:
    """Handle + gold equity-tick mark, ~4% frame width scaled later by scale2ref."""
    LOGO_DIR.mkdir(exist_ok=True)
    out = LOGO_DIR / f"wm_{vertical['key']}.png"
    if out.exists():
        return out
    c = colours()
    f = _font("headline", 44)
    handle = vertical["handle"]
    img = Image.new("RGBA", (900, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(10, 80), (35, 55), (55, 68), (95, 22)]  # the equity tick
    d.line(pts, fill=c["accent"], width=9, joint="curve")
    d.polygon([(95, 22), (72, 26), (91, 45)], fill=c["accent"])
    d.text((120, 28), handle, font=f, fill="#FFFFFF")
    img = img.crop(img.getbbox())
    img.save(out)
    return out


def make_logo_mark():
    """Standalone brand mark (assets/logo/mark.png + .svg), legible at 60px."""
    LOGO_DIR.mkdir(exist_ok=True)
    c = colours()
    img = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, 232, 232], radius=48, fill=c["bg"])
    d.line([(48, 176), (98, 118), (128, 142), (192, 62)], fill=c["accent"], width=18, joint="curve")
    d.polygon([(192, 62), (150, 70), (184, 104)], fill=c["accent"])
    img.save(LOGO_DIR / "mark.png")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">'
           f'<rect x="8" y="8" width="224" height="224" rx="48" fill="{c["bg"]}"/>'
           f'<path d="M48 176 L98 118 L128 142 L192 62" stroke="{c["accent"]}" stroke-width="18" fill="none" stroke-linejoin="round" stroke-linecap="round"/>'
           f'<path d="M192 62 L150 70 L184 104 Z" fill="{c["accent"]}"/></svg>')
    (LOGO_DIR / "mark.svg").write_text(svg, encoding="utf-8")


# ── karaoke ASS captions ─────────────────────────────────────────────────────
def _ass_time(s: float) -> str:
    h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def build_ass(words: list[dict], out: Path, offset: float = 0.0):
    from layout import FRAME_H, FRAME_W, SIDE_MARGIN, ass_margin_v, ass_max_font
    c = colours()
    def bgr(hexcol):
        r, g, b = hexcol[1:3], hexcol[3:5], hexcol[5:7]
        return f"&H00{b}{g}{r}".upper()
    fontsize = min(52, ass_max_font(lines=2))  # 2 wrapped lines can never leave the captions band
    header = f"""[Script Info]
PlayResX: {FRAME_W}
PlayResY: {FRAME_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Inter,{fontsize},{bgr(c['accent'])},&H00FFFFFF,&H00101318,&H80000000,-1,0,0,0,100,100,1.6,0,1,2.5,1,2,{SIDE_MARGIN},{SIDE_MARGIN},{ass_margin_v()},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # 4 words per line + letter-spacing 1.6 in the style: airier, easier to track
    lines, cur, cur_start = [], [], None
    for wd in words:
        if cur_start is None:
            cur_start = wd["start"]
        cur.append(wd)
        if len(cur) >= 4 or wd["word"].endswith((".", "!", "?", ":")):
            lines.append((cur_start, cur))
            cur, cur_start = [], None
    if cur:
        lines.append((cur_start, cur))
    events = []
    for i, (start, ws) in enumerate(lines):
        # end exactly when the next line starts (or at the last word)- two caption events
        # must NEVER coexist, or libass stacks them into a two-line overlap
        end = ws[-1]["end"]
        if i + 1 < len(lines):
            end = min(end + 0.12, lines[i + 1][0] - 0.01)
        text = "".join(f"{{\\k{max(1, int((w['end'] - w['start']) * 100))}}}{w['word']} " for w in ws).strip()
        events.append(f"Dialogue: 0,{_ass_time(start + offset)},{_ass_time(end + offset)},Karaoke,,0,0,0,,{text}")
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


# ── the composite ────────────────────────────────────────────────────────────
def assemble_reel(script: Script, insight: Insight, vo: dict, chart: dict,
                  mix_wav: Path | None, workdir: Path, vertical: dict,
                  timeline: dict) -> dict:
    """Timeline: hook card | chart segment | beat cards | CTA card | 0.5s loop-seam back to frame 0.

    Segment durations come from the orchestrator's schedule- the same one the VO was placed on.
    """
    vp = video_params()
    ff = ffmpeg_exe()
    hook_d = timeline["hook"]
    chart_d = timeline["chart"]
    beat_card_durs = timeline["beats"]
    cta_d = timeline["cta"]
    seam_d = timeline["seam"]

    cards = build_cards(script, insight, workdir, vertical)
    wm = build_watermark(vertical)

    segs, inputs, seg_durs = [], [], []
    def add_img(p, d):
        # -framerate must equal the output fps: zoompan re-times frames 1:1, so an image
        # looped at the default 25fps would come out 25/30 shorter and desync everything
        inputs.extend(["-loop", "1", "-framerate", str(vp["fps"]), "-t", f"{d:.3f}", "-i", str(p)])
        seg_durs.append(d)
    add_img(cards["hook"], hook_d)
    inputs.extend(["-i", str(chart["mp4"])])
    seg_durs.append(chart_d)
    for i, d in enumerate(beat_card_durs, start=1):
        key = f"beat{i}" if f"beat{i}" in cards else "cta"
        add_img(cards[key], d)
    add_img(cards["cta"], cta_d)
    add_img(cards["hook"], seam_d)  # loop seam: literal last frames = literal first frame

    n = len(seg_durs)
    fps = vp["fps"]
    # image segments (cards) get a slow Ken Burns zoom so no shot ever reads as frozen;
    # segment 1 is the chart mp4- it animates itself
    fc = ""
    for i in range(n):
        if i == 1:
            fc += f"[{i}:v]scale={vp['w']}:{vp['h']},setsar=1,fps={fps}[v{i}];"
        else:
            fc += (f"[{i}:v]scale={vp['w'] * 2}:{vp['h'] * 2},"
                   f"zoompan=z='1+0.0009*on':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                   f":s={vp['w']}x{vp['h']}:fps={fps},setsar=1[v{i}];")
    fc += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[base];"
    # watermark: 55% opacity, ~4% width via scale2ref, anti-crop drift (PRD expression)
    from layout import watermark_y_expr
    fc += (f"[{n}:v][base]scale2ref=w=iw*0.32:h=ow/mdar[wm][b2];"
           f"[wm]format=rgba,colorchannelmixer=aa=0.55[wmo];"
           f"[b2][wmo]overlay=x='if(lt(mod(t,20),10),40,W-w-40)':y={watermark_y_expr()}[marked];")
    ass = workdir / "captions.ass"
    # hook card already shows sentence 0 at display size- captions start from beat 1
    build_ass([w for w in vo["words"] if w.get("sentence", 1) >= 1], ass)
    ass_ff = str(ass).replace("\\", "/").replace(":", "\\:")
    fonts_ff = str(ROOT / "assets" / "fonts").replace("\\", "/").replace(":", "\\:")
    fc += f"[marked]subtitles='{ass_ff}':fontsdir='{fonts_ff}'[vout]"

    total = sum(seg_durs)
    out = workdir / "reel.mp4"
    cmd = [ff, "-y", *inputs, "-i", str(wm)]
    if mix_wav is not None:
        cmd += ["-i", str(mix_wav)]
    cmd += ["-filter_complex", fc, "-map", "[vout]"]
    if mix_wav is not None:
        cmd += ["-map", f"{n + 1}:a", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19",
            "-r", str(fps), str(out)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg assembly failed:\n{r.stderr.decode(errors='replace')[-2000:]}")
    if mix_wav is not None:
        _normalize_loudness(out)  # two-pass loudnorm on the FINAL mux- reels land at -14 LUFS exactly
    return {"mp4": out, "seconds": total, "timeline": dict(hook=hook_d, chart=chart_d,
            beats=beat_card_durs, cta=cta_d, seam=seam_d)}


def _normalize_loudness(mp4: Path, target_i: float = -14.0, tp: float = -1.5):
    """Measured (two-pass) loudnorm: analyse the muxed audio, then re-encode ONLY the audio
    with the measured values so integrated loudness hits the target dead-on. The one-pass
    normalisation upstream drifts once silent segments (the hook) enter the timeline.
    """
    import json as _json
    import re as _re
    ff = ffmpeg_exe()
    probe = subprocess.run([ff, "-i", str(mp4), "-af",
                            f"loudnorm=I={target_i}:TP={tp}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True).stderr
    m = _re.search(r"\{[^{}]+\}", probe[probe.rfind("Parsed_loudnorm"):] or "")
    if not m:
        return
    v = _json.loads(m.group(0))
    fixed = mp4.with_name(mp4.stem + "_ln.mp4")
    filt = (f"loudnorm=I={target_i}:TP={tp}:LRA=11:measured_I={v['input_i']}:"
            f"measured_TP={v['input_tp']}:measured_LRA={v['input_lra']}:"
            f"measured_thresh={v['input_thresh']}:offset={v['target_offset']}:linear=true")
    r = subprocess.run([ff, "-y", "-i", str(mp4), "-c:v", "copy", "-af", filt,
                        "-c:a", "aac", "-b:a", "192k", str(fixed)], capture_output=True)
    if r.returncode == 0 and fixed.exists():
        fixed.replace(mp4)


def make_thumbnail(chart_mp4: Path, script: Script, out: Path, chart_seconds: float):
    """Cover: the finished equity curve + hook text. The hook draws over a SOLID band
    covering the chart's title zone- cover text never overlaps chart text."""
    from layout import fit_text_block, zone
    ff = ffmpeg_exe()
    frame = out.with_suffix(".frame.png")
    subprocess.run([ff, "-y", "-sseof", "-0.2", "-i", str(chart_mp4), "-frames:v", "1", str(frame)],
                   capture_output=True, check=True)
    img = Image.open(frame).convert("RGB")
    d = ImageDraw.Draw(img)
    top, bot = zone("title")
    d.rectangle([0, 0, img.width, bot + 10], fill=colours()["bg"])  # blank the title band first
    band = (max(60, top - 120), bot)  # hook may also use the top-safe area- covers show full-bleed in the grid
    font, lines, y = fit_text_block(d, script.hook, str(font_path("headline_heavy")), 64, band)
    for line in lines:
        tw = d.textlength(line, font=font)
        d.text(((img.width - tw) / 2, y), line, font=font, fill="#FFFFFF")
        y += int(font.size * 1.25)
    img.save(out)
    frame.unlink()
