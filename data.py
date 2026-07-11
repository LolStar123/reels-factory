"""Data layer- IBKR first, graceful fallback chain, parquet cache, survivorship stamping.

Chain: IBKR (ib_insync, if TWS/Gateway reachable) -> yfinance -> stooq -> bundled sample parquet.
--dry-run / offline=True never touches the network (GEMINI-2 deterministic sample universe).
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from theme import ROOT, config

SAMPLE_DIR = ROOT / "state" / "marketdata" / "sample"
CACHE_DIR = ROOT / "state" / "marketdata"

# ticker aliases the sample universe understands
_ALIAS = {"BTC-USD": "BTC_USD", "BTC": "BTC_USD", "VIX": "VIXY", "^VIX": "VIXY"}


class DataUnavailable(Exception):
    pass


def _sample_path(ticker: str) -> Path:
    return SAMPLE_DIR / f"{_ALIAS.get(ticker, ticker).replace('-', '_')}.parquet"


def _load_sample(ticker: str) -> pd.DataFrame | None:
    p = _sample_path(ticker)
    if p.exists():
        df = pd.read_parquet(p)
        df.index = pd.to_datetime(df.index)
        return df
    return None


def _load_ibkr(ticker: str, years: int) -> pd.DataFrame | None:
    """Primary source. Requires TWS/IB Gateway running; returns None if unreachable."""
    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT", "7497"))
    cid = int(os.environ.get("IBKR_CLIENT_ID", "17"))
    try:
        from ib_insync import IB, Stock, util
        ib = IB()
        ib.connect(host, port, clientId=cid, timeout=4)
        bars = ib.reqHistoricalData(
            Stock(ticker, "SMART", "USD"), endDateTime="",
            durationStr=f"{min(years, 30)} Y", barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST", useRTH=True)
        ib.disconnect()
        if not bars:
            return None
        df = util.df(bars).set_index("date")
        df.index = pd.to_datetime(df.index)
        df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                "close": "Close", "volume": "Volume"})
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception:
        return None


def _load_yfinance(ticker: str, years: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(ticker, period=f"{years}y", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def _load_stooq(ticker: str) -> pd.DataFrame | None:
    try:
        import requests
        sym = ticker.lower() + (".us" if "-" not in ticker else "")
        r = requests.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=15)
        if r.status_code != 200 or not r.text.startswith("Date"):
            return None
        from io import StringIO
        df = pd.read_csv(StringIO(r.text), parse_dates=["Date"]).set_index("Date")
        return df
    except Exception:
        return None


def get_bars(ticker: str, years: int = 20, offline: bool = False) -> tuple[pd.DataFrame, str]:
    """Return (daily bars, source_tag). source_tag in {'ibkr','yfinance','stooq','sample'}.

    Cache-first: a cached non-sample series is reused (never hit a live API twice).
    """
    cache = CACHE_DIR / f"{_ALIAS.get(ticker, ticker).replace('-', '_')}_live.parquet"
    if not offline and cache.exists():
        df = pd.read_parquet(cache)
        df.index = pd.to_datetime(df.index)
        return df, "cache"
    if offline:
        df = _load_sample(ticker)
        if df is None:
            raise DataUnavailable(f"{ticker} not in bundled sample universe {sorted(p.stem for p in SAMPLE_DIR.glob('*.parquet'))}")
        return df, "sample"
    for loader, tag in ((lambda: _load_ibkr(ticker, years), "ibkr"),
                        (lambda: _load_yfinance(ticker, years), "yfinance"),
                        (lambda: _load_stooq(ticker), "stooq")):
        df = loader()
        if df is not None and len(df) > 250:
            df.to_parquet(cache)
            return df, tag
    df = _load_sample(ticker)
    if df is not None:
        return df, "sample"
    raise DataUnavailable(f"no source could serve {ticker}")


def get_universe(tickers: list[str], years: int = 20, offline: bool = False) -> tuple[dict[str, pd.DataFrame], str, bool]:
    """Fetch every ticker. Returns (bars_by_ticker, worst_source, survivorship_limited).

    survivorship_limited is True unless every series came from IBKR point-in-time data (CODEX-2).
    """
    out, sources = {}, set()
    for t in tickers:
        df, src = get_bars(t, years, offline)
        out[t] = df
        sources.add(src)
    order = ["ibkr", "cache", "yfinance", "stooq", "sample"]
    worst = max(sources, key=lambda s: order.index(s) if s in order else 99)
    survivorship_limited = sources != {"ibkr"}
    return out, worst, survivorship_limited


def closes_frame(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({t: df["Close"] for t, df in bars.items()}).sort_index().ffill().dropna(how="all")
