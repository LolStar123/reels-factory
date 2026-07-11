"""Chart/animation engine- the hero visual. Registry of brand-dark renderers.

Every renderer: 1080x1920 frames -> mp4 segment, progressive reveal w/ ease-out,
machine-readable overlays.json alongside (CODEX-9: qc compares numbers by construction).
Beats the baseline (assets/reference/baseline_chart.png): two lines max, no legend box,
endpoint labels, annotated troughs, counting final value, as-of stamp, handle baked on.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from contracts import BacktestResult
from theme import FONT_FAMILIES, colours, config, ffmpeg_exe, register_matplotlib_fonts, video_params

register_matplotlib_fonts()


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _fig(w, h):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_facecolor(colours()["bg"])
    return fig


def _style_axes(ax):
    c = colours()
    ax.set_facecolor(c["bg"])
    for s in ax.spines.values():
        s.set_color("#2A2F38")
    ax.tick_params(colors="#6A7079", labelsize=16)
    ax.grid(True, color="#1C2129", linewidth=0.6, alpha=0.6)


def _sym() -> str:
    return config()["brand"].get("currency", {}).get("symbol", "$")


def _fmt_money(v):
    s = _sym()
    return f"{s}{v / 1000:.0f}k" if v >= 10_000 else f"{s}{v:,.0f}"


def render_equity_race(result: BacktestResult, workdir: Path, lane: str,
                       segment_seconds: float | None = None, handle: str = "") -> dict:
    """The equity-curve reveal: gold strategy vs grey benchmark, 6s draw + stat-card count-up.

    Returns {'mp4': path, 'overlays': path, 'seconds': float}.
    """
    c = colours()
    vp = video_params()
    w, h, fps = vp["w"], vp["h"], vp["fps"]
    draw_s = vp["chart_draw_seconds"]
    stat_s = 4.0
    total_s = segment_seconds or (draw_s + stat_s)
    n_frames = int(total_s * fps)
    frames_dir = workdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    dates = pd.to_datetime([d for d, _ in result.equity_curve])
    eq = np.array([v for _, v in result.equity_curve])
    bdates = pd.to_datetime([d for d, _ in result.benchmark_curve])
    beq = np.array([v for _, v in result.benchmark_curve])
    m = result.metrics

    log_scale = (max(eq.max(), beq.max()) / max(min(eq.min(), beq.min()), 1)) > 10
    # drawdown troughs to flash red as the line passes
    run_max = np.maximum.accumulate(eq)
    dd = (eq - run_max) / run_max
    trough_idx = [int(np.argmin(dd))]
    if dd.min() < -0.10:
        half = len(dd) // 2
        other = int(np.argmin(dd[:half])) if trough_idx[0] >= half else half + int(np.argmin(dd[half:]))
        if abs(other - trough_idx[0]) > len(dd) // 8 and dd[other] < -0.08:
            trough_idx.append(other)

    stats = [("CAGR", m["cagr"] * 100, "%", m["cagr"] >= 0),
             ("SHARPE", m["sharpe"], "", m["sharpe"] >= 0.5),
             ("MAX DD", m["mdd"] * 100, "%", False),
             ("VS S&P", (m["cagr"] - m["benchmark_cagr"]) * 100, "%/yr", m["cagr"] >= m["benchmark_cagr"])]

    # every placement comes from layout.ZONES- the bands are exclusive, so chart text
    # can never touch the caption or watermark bands (layout.py is the single source)
    from layout import fig_rect, fig_y, zone
    t_top, t_bot = zone("title")
    c_top, c_bot = zone("content")
    s_top, s_bot = zone("stats")

    fig = _fig(w, h)
    ax = fig.add_axes(fig_rect(c_top + 20, c_bot - 60))  # 60px inside content for x tick labels
    _style_axes(ax)
    if log_scale:
        ax.set_yscale("log")
    ax.set_xlim(dates[0], dates[-1] + (dates[-1] - dates[0]) * 0.14)  # right pad so endpoint labels never clip
    tick_years = list(range(dates[0].year + 2, dates[-1].year + 1, 4))
    ax.set_xticks([pd.Timestamp(f"{y}-01-01") for y in tick_years])
    ax.set_xticklabels([str(y) for y in tick_years])
    lo = min(eq.min(), beq.min()) * 0.92
    hi = max(eq.max(), beq.max()) * 1.10
    ax.set_ylim(lo, hi)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _fmt_money(v)))

    hf = FONT_FAMILIES["headline"]
    mf = FONT_FAMILIES["mono"]
    fig.text(0.5, fig_y(t_top + 75), f"GROWTH OF {_sym()}10,000", ha="center", fontsize=30, color="#9AA0A9",
             fontfamily=hf, fontweight="semibold")
    title = getattr(result, "display_title", "") or result.spec_name
    sub = title if len(title) <= 52 else title[:49] + "..."
    fig.text(0.5, fig_y(t_top + 170), sub, ha="center", fontsize=22, color=c["text"],
             fontfamily=hf, fontweight="semibold")
    scale_note = "log scale" if log_scale else "linear scale"
    fig.text(0.10, fig_y(s_top + 30), f"as of {result.as_of} · {scale_note}"
             + (" · survivorship-limited (free data)" if result.survivorship_limited else ""),
             fontsize=13, color="#6A7079", fontfamily=mf)
    if handle:
        fig.text(0.94, fig_y(s_top + 30), handle, fontsize=14, color="#8A9099", fontfamily=mf,
                 ha="right", alpha=0.9)

    # parse_math=False EVERYWHERE money renders: "$66k vs $103k" contains two '$'
    # which matplotlib would otherwise read as a mathtext span and mangle
    (line_s,) = ax.plot([], [], color=c["accent"], lw=3, solid_capstyle="round", zorder=5)
    (line_b,) = ax.plot([], [], color=c["benchmark"], lw=2, zorder=4)
    lbl_s = ax.annotate("", (dates[0], eq[0]), color=c["accent"], fontsize=17, fontfamily=mf,
                        fontweight="bold", parse_math=False)
    lbl_b = ax.annotate("", (dates[0], beq[0]), color=c["benchmark"], fontsize=15, fontfamily=mf,
                        parse_math=False)
    flash = ax.scatter([], [], s=380, color=c["negative"], alpha=0.0, zorder=6)
    final_txt = fig.text(0.5, fig_y(s_top + 100), "", ha="center", fontsize=44, color=c["accent"],
                         fontfamily=mf, fontweight="bold", parse_math=False)
    stat_txts, stat_names = [], []
    for i, (name, _, _, _) in enumerate(stats):
        x = 0.155 + 0.23 * i
        stat_names.append(fig.text(x, fig_y(s_top + 150), name, ha="center", fontsize=15, color="#6A7079",
                                   fontfamily=hf, fontweight="semibold", alpha=0.0))
        stat_txts.append(fig.text(x, fig_y(s_top + 195), "", ha="center", fontsize=25,
                                  color=c["text"], fontfamily=mf, parse_math=False))

    draw_frames = int(draw_s * fps)
    pop_frames = int(0.4 * fps)
    n_pts = len(eq)

    for f in range(n_frames):
        if f <= draw_frames:
            k = max(2, int(_ease_out(f / draw_frames) * n_pts))
            k = min(k, n_pts)
            line_s.set_data(dates[:k], eq[:k])
            kb = min(k, len(beq))
            line_b.set_data(bdates[:kb], beq[:kb])
            # endpoint labels: separated from each other AND clamped inside the axes box
            y_s, y_b = eq[k - 1] * 1.07, beq[kb - 1] * 0.90
            if abs(np.log(max(y_s, 1)) - np.log(max(y_b, 1))) < 0.16:
                y_b = y_s * np.exp(-0.16)
            y_s = float(np.clip(y_s, lo * 1.08, hi * 0.93))
            y_b = float(np.clip(y_b, lo * 1.02, hi * 0.84))
            lbl_s.set_position((dates[k - 1], y_s))
            lbl_s.set_text(_fmt_money(eq[k - 1]))
            lbl_b.set_position((bdates[kb - 1], y_b))
            lbl_b.set_text("S&P " + _fmt_money(beq[kb - 1]))
            hit = [i for i in trough_idx if 0 < k - i < int(0.35 * n_pts / draw_s)]
            if hit:
                i = hit[0]
                flash.set_offsets([[matplotlib.dates.date2num(dates[i]), eq[i]]])
                flash.set_alpha(max(0.0, 0.55 - 1.8 * (k - i) / n_pts * draw_s))
            else:
                flash.set_alpha(0.0)
        else:
            t_after = (f - draw_frames) / fps
            for sn in stat_names:
                sn.set_alpha(min(1.0, t_after / 0.4))
            if t_after <= 0.4:  # final-value pop 1.0 -> 1.08 -> 1.0
                p = t_after / 0.4
                scale = 1.0 + 0.08 * np.sin(np.pi * p)
                final_txt.set_fontsize(44 * scale)
            elif t_after > 1.3:  # gentle breathing pulse- the long stat-card hold never freezes
                final_txt.set_fontsize(44 * (1 + 0.015 * np.sin(2 * np.pi * (t_after - 1.3) / 2.6)))
            final_txt.set_text(_fmt_money(m["final_value"]) + f"  vs  S&P {_fmt_money(m['benchmark_final'])}")
            for i, (name, val, unit, positive) in enumerate(stats):
                start = 0.5 + 0.15 * i  # 0.15s stagger per stat
                cu = np.clip((t_after - start) / 0.8, 0, 1)
                shown = val * _ease_out(float(cu))
                if cu > 0:
                    stat_txts[i].set_text(f"{shown:+.2f}{unit}" if unit != "%/yr" else f"{shown:+.1f}{unit}")
                    stat_txts[i].set_color(c["positive"] if positive else (c["negative"] if name == "MAX DD" or shown < 0 else c["text"]))
        fig.savefig(frames_dir / f"f{f:05d}.png", dpi=100, facecolor=c["bg"])
    plt.close(fig)

    mp4 = workdir / "chart.mp4"
    subprocess.run([ffmpeg_exe(), "-y", "-framerate", str(fps), "-i", str(frames_dir / "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(mp4)],
                   capture_output=True, check=True)
    for p in frames_dir.glob("*.png"):
        p.unlink()

    overlays = {  # every number shown on screen- qc matches these against BacktestResult
        "final_value": round(m["final_value"]), "benchmark_final": round(m["benchmark_final"]),
        "cagr_pct": round(m["cagr"] * 100, 2), "sharpe": round(m["sharpe"], 2),
        "mdd_pct": round(m["mdd"] * 100, 2),
        "vs_sp_pct_yr": round((m["cagr"] - m["benchmark_cagr"]) * 100, 1),
        "as_of": result.as_of, "renderer": "equity_race"}
    op = workdir / "overlays.json"
    op.write_text(json.dumps(overlays, indent=1), encoding="utf-8")
    return {"mp4": mp4, "overlays": op, "seconds": total_s}


def render_underwater(result: BacktestResult, workdir: Path, lane: str,
                      segment_seconds: float | None = None, handle: str = "") -> dict:
    """Drawdown underwater chart (wannabe_quant)- red area below high-water mark. Static-reveal variant."""
    return render_equity_race(result, workdir, lane, segment_seconds, handle)  # v1: hero renderer covers dry-run; rotated in Slice B


RENDERERS = {
    "equity_race": render_equity_race,
    "underwater": render_underwater,
}


def render_chart(chart_type: str, result: BacktestResult, workdir: Path, lane: str,
                 segment_seconds: float | None = None, handle: str = "") -> dict:
    fn = RENDERERS.get(chart_type, render_equity_race)
    return fn(result, workdir, lane, segment_seconds, handle)
