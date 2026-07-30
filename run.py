"""Orchestrator- the whole chain, staged checks, doctor preflight, machine-readable logs.

  python run.py --dry-run                 # bundled paper + bundled data, zero network/keys
  python run.py --doctor                  # preflight (CODEX-12)
  python run.py --check data|backtest|chart|package   # staged acceptance (CODEX-7)
  python run.py --paper <arxiv_id_or_url> # build from a specific paper
  python run.py --batch N                 # build N reels into the buffer
  python run.py --seed-from-quantihack    # ingest the 50-strategy launch buffer
  python run.py --refresh-trends          # stage 0
  python run.py --pull-insights           # stage 12
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from theme import ROOT, config, ffmpeg_exe, font_path, vertical as get_vertical

LOG = ROOT / "state" / "runs.jsonl"


def jlog(run_id: str, stage: str, **kw):
    """Machine-readable log keyed to the run id (GEMINI-8)- stage 12 correlates from these."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "run_id": run_id, "stage": stage, **kw}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{stage}] " + " ".join(f"{k}={v}" for k, v in kw.items() if k != "detail"))


# ── doctor (CODEX-12) ────────────────────────────────────────────────────────
def doctor() -> int:
    import importlib.util as iu
    import subprocess
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        ok = ok and passed

    print("run.py --doctor")
    try:
        ff = ffmpeg_exe()
        r = subprocess.run([ff, "-version"], capture_output=True, text=True)
        check("ffmpeg", r.returncode == 0, ff)
        enc = subprocess.run([ff, "-encoders"], capture_output=True, text=True).stdout
        check("libx264 + aac encoders", "libx264" in enc and "aac" in enc)
    except Exception as e:
        check("ffmpeg", False, str(e))
    for key in ("headline", "headline_heavy", "body", "body_medium", "mono", "mono_bold"):
        try:
            check(f"font {key}", font_path(key).exists())
        except SystemExit:
            check(f"font {key}", False)
    sample = ROOT / "state" / "marketdata" / "sample"
    check("sample market data", len(list(sample.glob("*.parquet"))) >= 5,
          f"{len(list(sample.glob('*.parquet')))} parquet files")
    check("sample paper", (ROOT / "assets" / "sample" / "sample_paper_trend_following.pdf").exists())
    check("sample strategy spec", (ROOT / "assets" / "sample" / "sample_strategy_spec.json").exists())
    piper = ROOT / "tools" / "piper" / "piper" / "piper.exe"
    kokoro = ROOT / "tools" / "kokoro" / "kokoro-v1.0.onnx"
    if piper.exists() or kokoro.exists():
        print("  PASS  local neural TTS  (" + ("piper" if piper.exists() else "kokoro") + ")")
    else:
        print("  SKIP  local neural TTS (optional models are not included in the public clone)")
    for mod in ("pandas", "numpy", "matplotlib", "yfinance", "feedparser", "fitz",
                "pydantic", "pyarrow", "PIL", "yaml"):
        check(f"import {mod}", iu.find_spec(mod) is not None)
    for d in ("state", "out"):
        p = ROOT / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("x")
            t.unlink()
            check(f"{d}/ writable", True)
        except Exception:
            check(f"{d}/ writable", False)
    import os
    if os.environ.get("IBKR_HOST"):
        import socket
        s = socket.socket()
        s.settimeout(2)
        try:
            s.connect((os.environ["IBKR_HOST"], int(os.environ.get("IBKR_PORT", "7497"))))
            check("IBKR reachable", True)
        except Exception:
            check("IBKR reachable", False, "TWS/Gateway not running- fallback chain will serve")
        finally:
            s.close()
    else:
        print("  SKIP  IBKR (not configured- fallback chain will serve)")
    print("doctor:", "ALL GREEN" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


# ── the chain ────────────────────────────────────────────────────────────────
def build_reel(paper, offline: bool, run_id: str, force_vertical: str | None = None,
               tts_online: bool = False, spec_override=None) -> str | None:
    """One paper -> one packaged reel. Returns slug or None (with the failure logged)."""
    import extract as ex
    import insight as ins
    import script as scr
    import voice as vc
    import audio as au
    import charts as ch
    import assemble as asb
    import qc as qcm
    import caption as capm
    import factcheck as fc
    import package as pk
    import ledger
    from backtest import run_backtest

    t0 = time.time()
    spec = spec_override or ex.extract_strategy(paper, offline)
    if spec is None:
        jlog(run_id, "extract", paper=paper.id, skipped="not mechanically testable")
        return None
    ok, why = ex.codeability_gate(spec)
    if not ok:
        jlog(run_id, "codeability", paper=paper.id, rejected=why)
        return None
    jlog(run_id, "extract", paper=paper.id, spec=spec.name, shape=spec.shape)

    if not offline and ins.is_repeat(spec.paper_ref):  # dry-run reuses the bundled fixture freely
        jlog(run_id, "dedup", paper=paper.id, skipped="used in last 30 days")
        return None

    result = run_backtest(spec, offline=offline)
    jlog(run_id, "backtest", sharpe=round(result.metrics["sharpe"], 2),
         verdict=result.verdict, source=result.data_source)

    insight = ins.build_insight(spec, result)
    vert = get_vertical(insight.lane if insight.lane != "both" else
                        (force_vertical or "high_finance"))
    if force_vertical:
        vert = get_vertical(force_vertical)
    script = scr.write_script(insight, result, spec, offline)
    jlog(run_id, "script", hook_id=script.hook_id, est=script.est_seconds, lane=vert["key"])

    slug = pk.make_slug(spec.name, vert["key"])
    workdir = ROOT / "state" / "work" / slug
    workdir.mkdir(parents=True, exist_ok=True)

    parts_info = vc.render_parts(script, workdir, offline and not tts_online)
    durs = [d for _, d, _ in parts_info["parts"]]  # [beat1, beat2, ..., cta]- the hook is SILENT
    jlog(run_id, "voice", engine=parts_info["engine"], sentences=len(durs))

    # visual timeline: brief silent hook card | chart (VO beats 1-2 play over it) |
    # beat cards | CTA | loop seam. Sentences are PLACED at segment starts- sync by construction.
    vcfg = config()["video"]
    draw_s = vcfg["chart_draw_seconds"]
    n_beats = len(script.beats)
    hook_d = float(vcfg.get("hook_seconds", 2.2))  # a couple of seconds, read not spoken
    b2_start_rel = max(draw_s + 0.3, durs[0] + 0.8)  # beat 2 lands on the stat-card reveal
    chart_d = max(draw_s + 3.5,
                  b2_start_rel + (durs[1] if n_beats > 1 else 0) + 0.8)
    beat_card_durs = [max(2.0, d + 0.5) for d in durs[2:n_beats]] if n_beats > 2 else []
    cta_d = max(2.5, durs[-1] + 0.5)
    seam_d = 0.5
    total = hook_d + chart_d + sum(beat_card_durs) + cta_d + seam_d
    starts = [hook_d + 0.3]                      # beat 1 as the chart starts drawing
    if n_beats > 1:
        starts.append(hook_d + b2_start_rel)     # beat 2 on the stat card
    t = hook_d + chart_d
    for d in beat_card_durs:
        starts.append(t + 0.25)
        t += d
    starts.append(t + 0.25)  # cta
    timeline = dict(hook=hook_d, chart=chart_d, beats=beat_card_durs, cta=cta_d, seam=seam_d)

    chart = ch.render_chart(insight.chart_type, result, workdir, vert["key"],
                            segment_seconds=chart_d, handle=vert["handle"])
    jlog(run_id, "chart", renderer=insight.chart_type, seconds=round(chart["seconds"], 1))

    vo = vc.place_parts(parts_info, starts, total, workdir)
    mix = au.mix_audio(vo["wav"], slug, total, workdir)
    track = au.pick_bed(slug)
    jlog(run_id, "audio", bed=(track.name if track else "none"), duration=round(total, 1))

    built = asb.assemble_reel(script, insight, vo, chart, mix, workdir, vert, timeline)
    jlog(run_id, "assemble", mp4=built["mp4"].name, seconds=round(built["seconds"], 1))

    thumb = workdir / "cover.png"
    try:
        asb.make_thumbnail(chart["mp4"], script, thumb, chart["seconds"])
    except Exception as e:
        jlog(run_id, "thumbnail", error=str(e)[:200])
        thumb = None

    fc_ok, fc_fails = fc.factcheck(script, result)
    qc_ok, qc_fails = qcm.run_qc(built["mp4"], chart["overlays"], result, script, workdir)
    all_fails = qc_fails + ([] if fc_ok else [f"FACTCHECK: {f}" for f in fc_fails])
    jlog(run_id, "qc", passed=qc_ok and fc_ok, fails=len(all_fails),
         detail="; ".join(all_fails[:6]))
    if not (qc_ok and fc_ok):
        ledger.log_failure(run_id, "qc", "; ".join(all_fails))

    cap = capm.build_caption(script, insight, result, vert["key"], slug,
                             trending_audio_note=vert.get("signature_audio", ""))
    script.caption = cap["caption"]
    pkg = pk.package_reel(slug, built["mp4"], thumb, script, insight, result, cap, vert,
                          qc_ok and fc_ok, all_fails, run_id, insight.chart_type,
                          built["seconds"], track.name if track else None)
    ins.mark_used(spec.paper_ref, vert["key"], insight.tone)
    jlog(run_id, "package", slug=slug, qc=pkg.qc_passed, took=round(time.time() - t0, 1))
    return slug


def sample_paper():
    from contracts import Paper
    return Paper(id="arXiv:1404.3274", title="Two Centuries of Trend Following",
                 authors=["Y. Lemperiere", "C. Deremble", "P. Seager", "M. Potters", "J.-P. Bouchaud"],
                 year=2014, source="bundled",
                 abstract="Trend following produces anomalously high Sharpe across two centuries and all asset classes.",
                 url="https://arxiv.org/abs/1404.3274", testability_score=0.95)


# ── staged checks (CODEX-7) ──────────────────────────────────────────────────
def staged_check(which: str) -> int:
    from extract import bundled_sample_spec
    run_id = f"check-{which}-{uuid.uuid4().hex[:6]}"
    if which == "data":
        import data
        bars, src, sl = data.get_universe(["SPY", "TLT", "GLD"], offline=True)
        print(f"data: {len(bars)} series from {src}, survivorship_limited={sl}, "
              f"SPY rows={len(bars['SPY'])}")
        return 0
    if which == "backtest":
        from backtest import run_backtest
        r = run_backtest(bundled_sample_spec(), offline=True)
        print(f"backtest: sharpe={r.metrics['sharpe']:.2f} cagr={r.metrics['cagr']:.3f} "
              f"mdd={r.metrics['mdd']:.2f} verdict={r.verdict}")
        return 0
    if which == "chart":
        import charts
        from backtest import run_backtest
        r = run_backtest(bundled_sample_spec(), offline=True)
        wd = ROOT / "state" / "work" / "_check_chart"
        wd.mkdir(parents=True, exist_ok=True)
        out = charts.render_chart("equity_race", r, wd, "high_finance", handle="@priced.in")
        print(f"chart: {out['mp4']} ({out['seconds']}s) + {out['overlays'].name}")
        return 0
    if which == "package":
        slug = build_reel(sample_paper(), offline=True, run_id=run_id)
        print(f"package: {slug}")
        return 0 if slug else 1
    print(f"unknown check {which}")
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--check", choices=["data", "backtest", "chart", "package"])
    ap.add_argument("--paper")
    ap.add_argument("--spec", metavar="JSON", help="render a hand-authored StrategySpec file- no LLM needed (specs/, seed bank)")
    ap.add_argument("--topic")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--tts-online", action="store_true",
                    help="allow edge-tts (free, keyless, needs internet) even in --dry-run")
    ap.add_argument("--vertical", choices=["high_finance", "wannabe_quant"])
    ap.add_argument("--seed-from-quantihack", action="store_true")
    ap.add_argument("--refresh-trends", action="store_true")
    ap.add_argument("--pull-insights", action="store_true")
    ap.add_argument("--approve-scan", action="store_true", help="ingest out/*/DECISION files")
    ap.add_argument("--review", metavar="SLUG", help="external quality review of a packaged reel ('latest' ok)")
    args = ap.parse_args()

    if args.review:
        import review
        slug = review.latest_slug() if args.review == "latest" else args.review
        sys.exit(review.review(slug) if slug else 2)

    if args.doctor:
        sys.exit(doctor())
    if args.check:
        sys.exit(staged_check(args.check))
    if args.seed_from_quantihack:
        import seeding
        sys.exit(seeding.seed())
    if args.refresh_trends:
        import trends
        sys.exit(trends.refresh())
    if args.pull_insights:
        import feedback
        sys.exit(feedback.pull_insights())
    if args.approve_scan:
        import package as pk
        for slug, dec, tag in pk.check_decisions():
            print(f"{slug}: {dec}" + (f" ({tag})" if tag else ""))
        sys.exit(0)

    import ledger
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    ledger.start_run(run_id, "dry-run" if args.dry_run else "live")
    built = []
    try:
        if args.spec:
            from contracts import Paper, StrategySpec
            spec = StrategySpec(**json.loads(Path(args.spec).read_text(encoding="utf-8-sig")))
            paper = Paper(id=f"spec:{Path(args.spec).stem}", title=spec.name,
                          source="hand-authored", url="", testability_score=1.0)
            slug = build_reel(paper, offline=True, run_id=run_id,
                              force_vertical=args.vertical, tts_online=args.tts_online,
                              spec_override=spec)
            if slug:
                built.append(slug)
        elif args.dry_run:
            lanes = [args.vertical] if args.vertical else ["high_finance", "wannabe_quant"]
            for i in range(args.batch):
                slug = build_reel(sample_paper(), offline=True, run_id=run_id,
                                  force_vertical=lanes[i % len(lanes)],
                                  tts_online=args.tts_online)
                if slug:
                    built.append(slug)
        else:
            import harvest
            papers = harvest.harvest(top_n=max(args.batch * 3, 6))
            for p in papers:
                if len(built) >= args.batch:
                    break
                try:
                    slug = build_reel(p, offline=False, run_id=run_id,
                                      force_vertical=args.vertical)
                    if slug:
                        built.append(slug)
                except Exception as e:
                    ledger.log_failure(run_id, "build", f"{p.id}: {e}")
                    jlog(run_id, "build", paper=p.id, error=str(e)[:300])
        ledger.finish_run(run_id, "done", f"built={len(built)}")
    except Exception as e:
        ledger.finish_run(run_id, "error", str(e)[:500])
        raise
    print(f"\nbuilt {len(built)} reel(s): {built}")
    for s in built:
        print(f"  out/{s}/  <- review + write DECISION (APPROVE / REJECT:<tag>)")
    sys.exit(0 if built else 1)


if __name__ == "__main__":
    main()
