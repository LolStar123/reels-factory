<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.svg">
  <img src="assets/banner-light.svg" alt="Reels Factory: paper in, evidence out, release locked">
</picture>

# Reels Factory

Reels Factory turns a quant paper into a QC-gated, 1080 x 1920 research reel.
It constrains the paper to a vetted strategy shape, runs a walk-forward backtest,
writes and renders the result, then holds the package for a human decision.

The difficult part is not making an MP4. It is keeping every spoken and visible
number traceable to one typed result while independent checks can still stop the
release. No package becomes publishable merely because the render completed.

## One paper, one measured result

<table>
  <tr>
    <td width="36%" align="center">
      <img src="docs/media/reel_demo.gif" width="260" alt="Animated demo reel at three times normal speed">
      <br><sub>31.8-second reel shown at 3x speed</sub>
    </td>
    <td width="64%">
      <code>RUN / OFFLINE FIXTURE</code><br><br>
      <strong>Paper</strong><br>
      Two Centuries of Trend Following, arXiv:1404.3274<br><br>
      <strong>Test window</strong><br>
      2004-2026, bundled sample data<br><br>
      <strong>Observed result</strong><br>
      8.71% CAGR / 0.83 Sharpe / -23.68% max drawdown<br><br>
      <strong>Benchmark</strong><br>
      SPY buy-and-hold / 10.89% CAGR<br><br>
      <strong>Gate</strong><br>
      <code>QC PASS / 0 FAILURES</code>
    </td>
  </tr>
</table>

Those numbers come from a verified offline run of the bundled fixture, not from
the paper's claimed performance. The sample-data result is explicitly marked
`survivorship_limited: true`. The content is educational and is not financial
advice.

## The system

```mermaid
flowchart LR
    subgraph research["RESEARCH"]
        A["Paper or constrained spec"] --> B["Codeability gate"]
        B --> C["Typed StrategySpec"]
    end
    subgraph evidence["EVIDENCE"]
        C --> D["Layered market data"]
        D --> E["Walk-forward backtest"]
        E --> F["Typed BacktestResult"]
    end
    subgraph production["PRODUCTION"]
        F --> G["Script and voice"]
        F --> H["Charts and overlays"]
        G --> I["9:16 assembly"]
        H --> I
    end
    subgraph control["CONTROL"]
        I --> J{"QC and fact-check"}
        J -->|"fail"| K["Rejected package"]
        J -->|"pass"| L["APPROVAL_PENDING"]
        L --> M{"Human DECISION"}
        M -->|"APPROVE"| N["Publish eligible"]
        M -->|"REJECT tag"| O["Learning loop"]
    end
```

The contracts move in one direction:
`Paper -> StrategySpec -> BacktestResult -> Insight -> Script -> ReelPackage`.
Machine-readable JSONL logs attach every stage to a `run_id`.

### What can stop a release

- [`extract.py`](extract.py) rejects papers that do not map to a supported
  momentum, mean-reversion, crossover, pairs, calendar, factor-sort, or
  volatility shape.
- [`qc.py`](qc.py) compares rendered overlay values with the backtest result and
  checks frame zones, media duration, codecs, audio, disclaimer text, and
  prohibited advice language.
- [`factcheck.py`](factcheck.py) independently re-derives claims from the result
  and paper instead of trusting the renderer.
- [`package.py`](package.py) writes `APPROVAL_PENDING` only after QC passes.
  Publishing also checks the approval ledger, so a render alone is insufficient.
- [`tools/redteam_test.py`](tools/redteam_test.py) proves that doctored numbers
  and advice phrases fail the gate.

## Run it offline

Python 3.12 and FFmpeg with `libx264` and `aac` are required. The public clone
includes the paper, nine sample parquet files, fonts, and strategy fixture. It
does not include the optional Piper or Kokoro model files.

```powershell
python -m pip install -r requirements.txt
python tools/make_bed.py
python run.py --doctor
python run.py --dry-run --vertical high_finance
```

The verified fixture run finishes without network access or API keys. If no
local TTS model is installed, it falls back to captions-only narration; the
generated bed still gives the QC gate a valid audio stream. Outputs appear under
`out/<slug>/` as an MP4, cover, caption, metadata, and, on a passing run, an
`APPROVAL_PENDING` file.

Useful isolated checks:

| Command | Scope |
|---|---|
| `python run.py --check data` | Load the bundled parquet series |
| `python run.py --check backtest` | Assert the fixture backtest |
| `python run.py --check chart` | Render the progressive chart and overlays |
| `python run.py --check package` | Build and gate one package |
| `python tools/redteam_test.py` | Exercise deliberate QC failures |

Live harvesting, online TTS, IBKR, LLM review, and Instagram publishing are
optional integrations. Their credentials belong in an untracked `.env`, never
in source.

## How the repository is structured

| Area | Responsibility |
|---|---|
| `contracts.py`, `extract.py`, `data.py`, `backtest.py` | Research constraints and evidence |
| `insight.py`, `script.py`, `voice.py`, `charts.py` | Editorial and visual production |
| `assemble.py`, `caption.py`, `cover.py`, `audio.py` | Media assembly |
| `qc.py`, `factcheck.py`, `compliance.py`, `review.py` | Release controls |
| `package.py`, `ledger.py`, `feedback.py` | Approval state and learning loop |
| `assets/sample/`, `state/marketdata/sample/` | Reproducible offline fixture |

The runtime directories `out/`, `state/work/`, and local voice models are
deliberately excluded. The music bed is reproducible with
[`tools/make_bed.py`](tools/make_bed.py).

## Contributing

Keep changes evidence-first. Add a fixture when introducing a strategy shape,
keep render values derived from `BacktestResult`, and add a failing red-team case
before changing a gate. Run the staged checks and the red-team test before
opening a pull request.

MIT licensed. See [`LICENSE`](LICENSE).
