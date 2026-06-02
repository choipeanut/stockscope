"""OHLCV price collectors for KOSDAQ (pykrx/finance-datareader) and NASDAQ (yfinance)."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Literal

import pandas as pd

from app.collectors import cache

Market = Literal["KOSDAQ", "KOSPI", "NASDAQ"]

# TTL per spec: OHLCV US 15 min, KR 5 min intraday
_TTL = {"KOSDAQ": 5 * 60, "KOSPI": 5 * 60, "NASDAQ": 15 * 60}

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


def _make_yf_session(timeout: int = 20):
    """yfinance용 requests.Session — 각 HTTP 요청에 timeout 적용."""
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })
    # requests.Session.send 에 기본 timeout 주입
    _orig_send = session.send

    def _send_with_timeout(*args, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return _orig_send(*args, **kwargs)

    session.send = _send_with_timeout  # type: ignore[method-assign]
    return session


def _fetch_kr(ticker: str, start: str, end: str) -> pd.DataFrame:
    """한국 주식 OHLCV 취득. pykrx → FinanceDataReader → yfinance .KS/.KQ 순서로 폴백."""
    # Method 1: pykrx (skip when KRX credentials are absent — login attempt
    # blocks for ~10 s before failing, making cold-cache serial loads very slow)
    import os as _os
    if _os.environ.get("KRX_ID") and _os.environ.get("KRX_PW"):
        try:
            from pykrx import stock as pykrx_stock
            df = pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass

    # Method 2: FinanceDataReader
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, start, end)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # Method 3: yfinance — try .KS (KOSPI) then .KQ (KOSDAQ) with actual date range.
    # start is "YYYYMMDD" string → convert to "YYYY-MM-DD" for yfinance.
    import yfinance as yf
    yf_start = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    session = _make_yf_session(20)
    for suffix in (".KS", ".KQ"):
        try:
            tk = yf.Ticker(ticker + suffix, session=session)
            df = tk.history(start=yf_start, auto_adjust=True)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    return pd.DataFrame()


def _fetch_us(ticker: str, period_days: int, retries: int = 2) -> pd.DataFrame:
    import time

    import yfinance as yf

    session = _make_yf_session(20)  # 20초 HTTP 타임아웃
    last_err: Exception = RuntimeError("unknown")
    for attempt in range(retries):
        try:
            tk = yf.Ticker(ticker, session=session)
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

    if market in ("KOSDAQ", "KOSPI"):
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
