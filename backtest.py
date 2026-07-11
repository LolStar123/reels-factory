"""Backtester- the quantihack walk-forward engine, lifted + generalised (PRD PRIOR ART: do not reinvent).

Executes a StrategySpec (constrained DSL shapes) over real bars, vs the benchmark,
with slippage, no look-ahead (positions shifted 1 day), and the survivorship-limited
stamp on any non-IBKR data path (CODEX-2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import data as datalayer
from contracts import BacktestResult, StrategySpec
from theme import config

CAP = 10_000  # growth-of-$10k framing for reels (currency symbol/word from config)
SLIP_BPS = 5  # flat per-side slippage


# ── engine (lifted from quantihack_alt_data_50.py) ─────────────────────────────
def bt_multi(wdf: pd.DataFrame, cdf: pd.DataFrame, capital=CAP, slip=SLIP_BPS) -> pd.Series:
    common = wdf.index.intersection(cdf.index)
    w = wdf.loc[common].fillna(0)
    c = cdf.loc[common].ffill()
    dr = c.pct_change().fillna(0)
    turnover = w.diff().abs().sum(axis=1).fillna(0)
    cost = turnover * slip / 10_000
    port_ret = (w.shift(1).fillna(0) * dr).sum(axis=1) - cost
    return capital * (1 + port_ret).cumprod()


def metrics(eq: pd.Series, capital=CAP) -> dict:
    if eq is None or len(eq) < 5:
        return {}
    eq = eq.astype(float)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    if yrs < 0.02:
        return {}
    cagr = (eq.iloc[-1] / capital) ** (1 / yrs) - 1 if yrs > 0 else 0
    dr = eq.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    down = dr[dr < 0]
    sortino = dr.mean() / down.std() * np.sqrt(252) if len(down) > 0 and down.std() > 0 else 0
    dd = (eq - eq.cummax()) / eq.cummax()
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    active = dr[dr.abs() > 1e-8]
    hit_rate = (active > 0).mean() if len(active) > 0 else 0
    yearly = eq.resample("YE").last().pct_change().dropna()
    best_year = float(yearly.max()) if len(yearly) else 0.0
    worst_year = float(yearly.min()) if len(yearly) else 0.0
    return dict(cagr=float(cagr), sharpe=float(sharpe), sortino=float(sortino), vol=float(vol),
                mdd=float(mdd), calmar=float(calmar), hit_rate=float(hit_rate),
                best_year=best_year, worst_year=worst_year,
                final_value=float(eq.iloc[-1]), total_ret=float(eq.iloc[-1] / eq.iloc[0] - 1))


# ── shape executors: StrategySpec.params -> daily weight frame ──────────────────
def _rebalance_mask(idx: pd.DatetimeIndex, freq: str) -> pd.Series:
    s = pd.Series(1, index=idx)
    if freq == "daily":
        return s.astype(bool)
    grouper = {"weekly": "W", "monthly": "ME"}.get(freq, "ME")
    last = s.groupby(pd.Grouper(freq=grouper)).tail(1).index
    return pd.Series(idx.isin(last), index=idx)


def _hold_between_rebalances(raw: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    held = raw.where(mask, np.nan).ffill().fillna(0)
    return held


def _shape_momentum(spec, closes):
    p = spec.params
    look = int(p.get("lookback_m", 12)) * 21
    skip = int(p.get("skip_m", 0)) * 21
    long_short = bool(p.get("long_short", False))
    mom = closes.shift(skip).pct_change(look - skip)
    if p.get("cross_sectional", False) and closes.shape[1] > 2:
        k = max(1, int(closes.shape[1] * float(p.get("top_fraction", 0.3))))
        rank = mom.rank(axis=1, ascending=False)
        w = (rank <= k).astype(float)
        if long_short:
            w = w - (mom.rank(axis=1) <= k).astype(float)
    else:  # time-series momentum: sign of trailing return per asset
        w = (mom > 0).astype(float)
        if long_short:
            w = np.sign(mom).fillna(0)
            w = pd.DataFrame(w, index=closes.index, columns=closes.columns)
    return w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)


def _shape_mean_reversion(spec, closes):
    p = spec.params
    n = int(p.get("lookback_d", 20))
    z_in = float(p.get("entry_z", -1.5))
    z_out = float(p.get("exit_z", 0.0))
    m = closes.rolling(n).mean()
    sd = closes.rolling(n).std()
    z = (closes - m) / sd
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    for col in closes.columns:
        in_trade = False
        zc = z[col]
        vals = np.zeros(len(zc))
        for i in range(len(zc)):
            if not in_trade and zc.iat[i] <= z_in:
                in_trade = True
            elif in_trade and zc.iat[i] >= z_out:
                in_trade = False
            vals[i] = 1.0 if in_trade else 0.0
        w[col] = vals
    return w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)


def _shape_crossover(spec, closes):
    p = spec.params
    fast, slow = int(p.get("fast_d", 50)), int(p.get("slow_d", 200))
    w = (closes.rolling(fast).mean() > closes.rolling(slow).mean()).astype(float)
    return w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)


def _shape_pairs(spec, closes):
    p = spec.params
    if closes.shape[1] < 2:
        raise ValueError("pairs shape needs 2 tickers")
    a, b = closes.columns[:2]
    n = int(p.get("lookback_d", 60))
    spread = np.log(closes[a]) - np.log(closes[b])
    z = (spread - spread.rolling(n).mean()) / spread.rolling(n).std()
    entry = float(p.get("entry_z", 2.0))
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    w.loc[z < -entry, a], w.loc[z < -entry, b] = 0.5, -0.5
    w.loc[z > entry, a], w.loc[z > entry, b] = -0.5, 0.5
    return w.replace(0, np.nan).ffill(limit=int(p.get("max_hold_d", 20))).fillna(0)


def _shape_calendar(spec, closes):
    p = spec.params
    window = p.get("window", "turn_of_month")  # turn_of_month | monday | month_days
    w = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    if window == "monday":
        mask = closes.index.dayofweek == 0
    elif window == "month_days":
        days = set(p.get("days", [1, 2, 3]))
        mask = pd.Index(closes.index.day).isin(days)
    else:  # turn of month: last 2 + first 3 trading days
        dom = pd.Series(np.arange(len(closes)), index=closes.index)
        by_m = dom.groupby(pd.Grouper(freq="ME"))
        mask = pd.Series(False, index=closes.index)
        for _, g in by_m:
            if len(g) >= 5:
                mask.loc[g.index[-2:]] = True
                mask.loc[g.index[:3]] = True
        mask = mask.values
    w.loc[mask, :] = 1.0 / closes.shape[1]
    return w


def _shape_factor_sort(spec, closes):
    p = spec.params
    metric = p.get("metric", "vol")  # vol | return
    n = int(p.get("lookback_d", 63))
    k = max(1, int(closes.shape[1] * float(p.get("top_fraction", 0.3))))
    if metric == "vol":
        score = -closes.pct_change().rolling(n).std()  # low-vol premium: prefer low vol
    else:
        score = closes.pct_change(n)
    rank = score.rank(axis=1, ascending=False)
    w = (rank <= k).astype(float)
    return w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)


def _shape_vol(spec, closes):
    p = spec.params
    target = float(p.get("target_vol", 0.10))
    n = int(p.get("lookback_d", 21))
    rv = closes.pct_change().rolling(n).std() * np.sqrt(252)
    lev = (target / rv).clip(upper=float(p.get("max_leverage", 1.0)))
    w = lev.fillna(0)
    return w.div(closes.shape[1])


SHAPES = {
    "momentum": _shape_momentum,
    "mean_reversion": _shape_mean_reversion,
    "crossover": _shape_crossover,
    "pairs": _shape_pairs,
    "calendar": _shape_calendar,
    "factor_sort": _shape_factor_sort,
    "vol": _shape_vol,
}


def run_backtest(spec: StrategySpec, offline: bool = False, years: int | None = None) -> BacktestResult:
    cfg = config()
    years = years or int(cfg["research"]["min_backtest_years"]) * 2  # pull long, show honest window
    bench_ticker = cfg["research"]["benchmark"].split()[0]

    bars, source, surv_limited = datalayer.get_universe(spec.universe, years, offline)
    closes = datalayer.closes_frame(bars)
    bench_bars, bench_src, _ = datalayer.get_universe([bench_ticker], years, offline)
    bench_close = bench_bars[bench_ticker]["Close"]

    raw_w = SHAPES[spec.shape](spec, closes)
    mask = _rebalance_mask(closes.index, spec.rebalance)
    w = _hold_between_rebalances(raw_w, mask) if spec.rebalance != "daily" else raw_w
    # no look-ahead: bt_multi applies w.shift(1) internally

    eq = bt_multi(w, closes).dropna()
    common = eq.index.intersection(bench_close.index)
    eq = eq.loc[common]
    bench_eq = CAP * (1 + bench_close.loc[common].pct_change().fillna(0)).cumprod()

    m = metrics(eq)
    bm = metrics(bench_eq)
    m["benchmark_cagr"] = bm.get("cagr", 0)
    m["benchmark_final"] = bm.get("final_value", CAP)
    m["benchmark_sharpe"] = bm.get("sharpe", 0)
    m["benchmark_mdd"] = bm.get("mdd", 0)
    excess = m["cagr"] - m["benchmark_cagr"]
    vs = f"{excess * 100:+.1f}%/yr vs {bench_ticker} buy & hold"
    if m["mdd"] < bm.get("mdd", 0):
        vs += f", deeper drawdown ({m['mdd'] * 100:.0f}% vs {bm.get('mdd', 0) * 100:.0f}%)"

    # verdict: in-sample vs final-third out-of-sample degradation
    third = len(eq) // 3
    oos = metrics((eq.iloc[-third:] / eq.iloc[-third]) * CAP) if third > 260 else m
    if m["sharpe"] > 0.5 and oos.get("sharpe", 0) > 0.3 and excess > 0:
        verdict = "held up"
    elif oos.get("sharpe", 1) < 0 or m["sharpe"] < 0.1:
        verdict = "broke down out-of-sample"
    else:
        verdict = "underwhelmed"

    step = max(1, len(eq) // 500)  # thin curves for the contract payload
    return BacktestResult(
        spec_name=spec.name, display_title=spec.display_title,
        paper_ref=spec.paper_ref, metrics=m,
        claimed_result=spec.claimed_result,
        equity_curve=[(d.strftime("%Y-%m-%d"), float(v)) for d, v in eq.iloc[::step].items()],
        benchmark_curve=[(d.strftime("%Y-%m-%d"), float(v)) for d, v in bench_eq.iloc[::step].items()],
        trades_summary={"rebalance": spec.rebalance, "universe": spec.universe,
                        "avg_gross_exposure": float(w.abs().sum(axis=1).mean()),
                        "params": spec.params,  # factcheck: rule parameters are legitimate spoken numbers
                        "rule_text": f"{spec.signal_rule} {spec.plain_rule} {spec.lookback}"},
        vs_benchmark=vs, verdict=verdict, data_source=source,
        survivorship_limited=surv_limited,
        as_of=eq.index[-1].strftime("%Y-%m-%d"),
        window=f"{eq.index[0].year}-{eq.index[-1].year}",
    )
