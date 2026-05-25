"""OHLCV price collectors for KOSDAQ (pykrx/finance-datareader) and NASDAQ (yfinance)."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Literal

import pandas as pd

from app.collectors import cache

Market = Literal["KOSDAQ", "NASDAQ"]

# TTL per spec: OHLCV US 15 min, KR 5 min intraday
_TTL = {"KOSDAQ": 5 * 60, "NASDAQ": 15 * 60}

_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame, market: Market) -> pd.DataFrame:
    """Rename columns to spec schema and ensure index is date ascending."""
    # yfinance may have multi-level columns — flatten first
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]

    # Move date index to column if needed (pykrx returns DatetimeIndex)
    if "date" not in df.columns and df.index.name is not None:
        df = df.reset_index()

    # Build column rename map — handle both English and Korean names
    kr_map = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
    en_map = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
    # Detect date column by name keywords
    date_keywords = {"date", "날짜", "일자", "index"}

    col_map: dict[str, str] = {}
    for c in df.columns:
        if c in kr_map:
            col_map[c] = kr_map[c]
        elif str(c).lower() in en_map:
            col_map[c] = en_map[str(c).lower()]
        elif str(c).lower() in date_keywords or (df.index.name and str(c) == str(df.index.name)):
            col_map[c] = "date"

    # If no date column found, try to detect it by parsing values
    if "date" not in col_map.values():
        # Guess: first column that isn't numeric is the date
        for c in df.columns:
            try:
                pd.to_datetime(df[c].iloc[:3])
                col_map[c] = "date"
                break
            except Exception:
                pass

    df = df.rename(columns=col_map)

    if "date" not in df.columns:
        raise ValueError("Could not identify date column in DataFrame")

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["market"] = market

    present = [c for c in _REQUIRED_COLS if c in df.columns]
    df = df[present + ["market"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _fetch_kr(ticker: str, start: str, end: str) -> pd.DataFrame:
    from pykrx import stock as pykrx_stock

    df = pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)
    if df is None or df.empty:
        # Fallback to finance-datareader
        import FinanceDataReader as fdr

        df = fdr.DataReader(ticker, start, end)
    return df


def _fetch_us(ticker: str, period_days: int, retries: int = 3) -> pd.DataFrame:
    import time

    import yfinance as yf

    last_err: Exception = RuntimeError("unknown")
    for attempt in range(retries):
        try:
            tk = yf.Ticker(ticker)
            df = tk.history(period=f"{period_days}d", auto_adjust=True)
            return df
        except Exception as e:
            last_err = e
            # Rate limit — back off before retry
            if "RateLimit" in type(e).__name__ or "429" in str(e):
                time.sleep(5 * (attempt + 1))
            else:
                raise
    raise last_err


def get_ohlcv(ticker: str, market: Market, period_days: int = 365) -> pd.DataFrame:
    """
    Return normalized OHLCV DataFrame with columns: date, open, high, low, close, volume, market.
    Raises ValueError for unknown/delisted tickers (empty data).
    Serves from TTL cache when available.
    """
    cache_key = f"ohlcv:{market}:{ticker}:{period_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        payload, _ = cached
        df = pd.read_json(io.StringIO(payload), orient="records")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days + 30)  # buffer for weekends/holidays

    if market == "KOSDAQ":
        raw = _fetch_kr(ticker, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    else:
        raw = _fetch_us(ticker, period_days + 30)

    if raw is None or raw.empty:
        raise ValueError(f"ticker not found: {ticker}")

    df = _normalize(raw, market)

    if df.empty or len(df) < 1:
        raise ValueError(f"ticker not found: {ticker}")

    payload_json = df.to_json(orient="records", date_format="iso")
    cache.set(cache_key, payload_json, _TTL[market])

    return df
