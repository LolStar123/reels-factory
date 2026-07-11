"""Typed schemas crossing stage boundaries (CODEX-3)- the spine of the pipeline.

Every stage consumes and returns these models; nothing passes loose dicts between modules.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

StrategyShape = Literal[
    "momentum", "mean_reversion", "crossover", "pairs", "calendar", "factor_sort", "vol"
]
Lane = Literal["high_finance", "wannabe_quant", "both"]
Tone = Literal["debunk", "confirm", "surprise"]


class Paper(BaseModel):
    id: str                              # arxiv id / DOI / title-hash
    title: str
    authors: list[str] = []
    year: int = 0
    abstract: str = ""
    full_text: Optional[str] = None
    pdf_url: Optional[str] = None
    source: str = "manual"
    url: str = ""
    testability_score: float = 0.0       # 0-1 from the stage-1 ranker


class StrategySpec(BaseModel):
    """Constrained DSL- a paper maps onto a vetted shape, never arbitrary code (CODEX-4/GEMINI-7)."""
    name: str
    hypothesis: str = ""
    shape: StrategyShape
    universe: list[str]
    signal_rule: str                     # human-readable statement of the rule
    plain_rule: str = ""                 # ONE plain-English sentence, zero jargon, digits not words- what the reel says
    display_title: str = ""              # short viewer-facing name, e.g. "The 12-Month Trend Rule" (not the lab label)
    params: dict = Field(default_factory=dict)
    entry: str = ""
    exit: str = ""
    rebalance: str = "monthly"           # daily | weekly | monthly
    position_sizing: str = "equal_weight"
    lookback: str = ""
    claimed_result: str = ""
    paper_ref: str = ""
    codeable: bool = True                # codeability-gate verdict


class BacktestResult(BaseModel):
    spec_name: str
    display_title: str = ""              # viewer-facing name carried from the spec
    paper_ref: str = ""
    metrics: dict                        # cagr, sharpe, sortino, mdd, hit_rate, calmar, best_year, worst_year...
    claimed_result: str = ""
    equity_curve: list[tuple[str, float]]
    benchmark_curve: list[tuple[str, float]]
    trades_summary: dict = Field(default_factory=dict)
    vs_benchmark: str = ""
    verdict: Literal["held up", "underwhelmed", "broke down out-of-sample"]
    data_source: str = "sample"
    survivorship_limited: bool = True    # CODEX-2 stamp; only IBKR point-in-time data clears it
    as_of: str = ""                      # data date, baked onto the chart (NICHE 8)
    window: str = ""                     # honest backtest window, e.g. "2004-2026"


class Insight(BaseModel):
    title: str
    angle: str
    hook_idea: str
    key_points: list[str]
    chart_type: str = "equity_race"
    chart_needed: bool = True
    risk_flag: bool = False
    lane: Lane = "high_finance"
    tone: Tone = "debunk"                # NICHE 4 variety enforcement tracks this
    smart_term: str = ""                 # the insider concept this reel teaches (rotated, evidence-picked)
    smart_line: str = ""                 # the spoken sentence delivering it


class Script(BaseModel):
    hook: str
    hook_number: str = ""                # the BIG money number on the hook card (visual hook)
    beats: list[str]
    cta: str
    on_screen_text: list[str] = []
    caption: str = ""
    hashtags: list[str] = []
    est_seconds: float = 32.0
    beat_timings: list[tuple[float, float]] = []
    cites_paper: str = ""
    hook_id: str = ""                    # hook-bank structure used (stage-12 training signal)


class ReelPackage(BaseModel):
    slug: str
    vertical: str
    mp4_path: str
    thumbnail_path: str = ""
    caption_txt: str = ""
    meta: dict = Field(default_factory=dict)
    qc_passed: bool = False
    approval: Literal["pending", "approved", "rejected"] = "pending"
    reject_tag: Optional[str] = None     # GEMINI-11 controlled vocabulary
