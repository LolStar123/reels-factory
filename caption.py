"""Caption & SEO metadata engine (module 13)- a proper engine, not a string.

Order (NICHE 3): our thought-provoking take FIRST -> citation -> disclaimer -> save/share
nudge only if room. First line is its own scroll-stopper (IG truncates the rest).
"""
from __future__ import annotations

import hashlib

from contracts import BacktestResult, Insight, Script
from theme import config

BROAD = ["#investing", "#stockmarket", "#finance", "#trading", "#personalfinance", "#money"]
NICHE = ["#quant", "#backtest", "#algotrading", "#quantfinance", "#fintok", "#investingtips",
         "#stocktok", "#dividends", "#etf", "#sp500", "#riskmanagement", "#financialliteracy"]
BRANDED = {"high_finance": ["#pricedin"], "wannabe_quant": ["#overfitquant"]}
NUDGES = {"high_finance": "Save this for the next dip.",
          "wannabe_quant": "Send this to your day-trader mate."}


def _rotate(pool: list[str], slug: str, k: int) -> list[str]:
    seed = int(hashlib.sha1(slug.encode()).hexdigest(), 16)
    idx = seed % len(pool)
    return [pool[(idx + i) % len(pool)] for i in range(k)]


def build_caption(script: Script, insight: Insight, result: BacktestResult,
                  lane: str, slug: str, trending_audio_note: str = "") -> dict:
    cfg = config()
    disclaimer = cfg["compliance"]["hard_disclaimer"]
    m = result.metrics

    gap = round(abs(m["benchmark_final"] - m["final_value"]) / 100) * 100  # matches the hook card
    win = result.window.split("-")
    span = f"{int(win[1]) - int(win[0])} years" if len(win) == 2 else result.window
    takes_hf = {  # high_finance lane: money language, zero Greek
        "debunk": (f"Everyone quotes this strategy. {span} of real data say it made "
                   f"${gap:,.0f} less than doing nothing- and still put you through a "
                   f"{abs(m['mdd']) * 100:.0f}% drop. The implementation gap is undefeated."),
        "confirm": ("I test these expecting to bust them. This one survived- and almost "
                    "nothing survives. Know the drawdown before you copy it."),
        "surprise": (f"Losing to buy-and-hold isn't the same as being wrong- this cut the worst "
                     f"drop to {abs(m['mdd']) * 100:.0f}%. Returns are what you brag about; "
                     "drawdowns are what you live through."),
    }
    takes_wq = {  # wannabe_quant lane: the Greek is the flex
        "debunk": (f"Academic Sharpe is a lab number. Net of costs this ran {m['sharpe']:.2f}- "
                   f"{'ahead of' if m['cagr'] > m['benchmark_cagr'] else 'behind'} the index, "
                   f"with a {abs(m['mdd']) * 100:.0f}% max drawdown. Implementation gap, every time."),
        "confirm": (f"Went in expecting to debunk it. Sharpe {m['sharpe']:.2f} out of sample- "
                    "the paper survives contact with reality. Base rate for that: near zero."),
        "surprise": (f"Underperforms the index, but the drawdown profile is the story- "
                     f"{abs(m['mdd']) * 100:.0f}% worst case. Optimise what you can live through."),
    }
    take = (takes_hf if lane == "high_finance" else takes_wq)[insight.tone]

    hashtags = _rotate(BROAD, slug, 4) + _rotate(NICHE, slug, 6) + BRANDED.get(lane, [])
    parts = [take, f"Tested: {script.cites_paper}.", disclaimer]
    if result.survivorship_limited:
        parts.insert(2, "Free-data backtest- survivorship-limited.")
    body = "\n\n".join(parts)
    nudge = NUDGES.get(lane, "")
    if len(body) + len(nudge) + len(" ".join(hashtags)) + 4 < 2200 and nudge:
        body += "\n\n" + nudge
    caption = (body + "\n\n" + " ".join(hashtags[:30]))[:2200]
    # keep the citation even if trimmed
    if script.cites_paper not in caption:
        caption = (take[:800] + f"\n\nTested: {script.cites_paper}.\n{disclaimer}")[:2200]

    alt_text = (f"Dark-themed animated chart: {result.spec_name} equity curve in gold vs S&P 500 in grey, "
                f"growth of 10 thousand dollars {result.window}; stat card with CAGR, Sharpe and max drawdown.")
    return {"caption": caption, "hashtags": hashtags[:30], "alt_text": alt_text,
            "trending_audio_note": trending_audio_note}
