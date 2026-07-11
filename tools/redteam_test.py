# Honesty red-team (acceptance step): a doctored overlay MUST fail QC; an advice phrase
# MUST fail the lint. Run after any change to qc.py / compliance.py / charts.py.
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest import run_backtest            # noqa: E402
from compliance import lint_text             # noqa: E402
from extract import bundled_sample_spec      # noqa: E402
from qc import run_qc                        # noqa: E402

fails = 0

# 1) banned-phrase lint
ok, why = lint_text("Here's why you should buy this dip right now")
if ok:
    print("RED-TEAM FAIL: advice phrase passed the lint")
    fails += 1
else:
    print(f"lint correctly failed: {why}")

# 2) doctored on-screen number -> QC must fail
work = [p for p in sorted((ROOT / "state" / "work").glob("*/overlays.json"))
        if (p.parent / "reel.mp4").exists()]
if not work:
    print("no built reel found- run a dry-run first")
    sys.exit(2)
overlays_path = work[-1]
workdir = overlays_path.parent
mp4 = workdir / "reel.mp4"
result = run_backtest(bundled_sample_spec(), offline=True)

doctored = json.loads(overlays_path.read_text(encoding="utf-8"))
doctored["sharpe"] = 1.80  # the lie the paper told
tampered = workdir / "overlays_tampered.json"
tampered.write_text(json.dumps(doctored), encoding="utf-8")

class _FakeScript:  # minimal Script stand-in for the qc call
    hook = "test"; beats = ["a"]; cta = "b"; caption = "Educational only. Not financial advice. cite"
    cites_paper = "cite"

qc_ok, qc_fails = run_qc(mp4, tampered, result, _FakeScript, workdir)
if qc_ok or not any("HONESTY" in f for f in qc_fails):
    print(f"RED-TEAM FAIL: tampered sharpe survived QC ({qc_fails})")
    fails += 1
else:
    print(f"QC correctly caught the tampered stat: {[f for f in qc_fails if 'HONESTY' in f]}")

print("red-team:", "PASS" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
