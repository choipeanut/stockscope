"""T2 verify: schema, row count, and cache-hit for both markets."""
import time

import pytest

from app.collectors.prices import get_ohlcv

REQUIRED_COLS = {"date", "open", "high", "low", "close", "volume", "market"}


@pytest.mark.parametrize(
    "ticker,market",
    [
        ("AAPL", "NASDAQ"),
        ("005930", "KOSDAQ"),  # Samsung Electronics (KOSPI/KOSDAQ listed)
    ],
)
def test_schema_and_row_count(ticker, market):
    df = get_ohlcv(ticker, market, period_days=365)
    assert not df.empty, "DataFrame must not be empty"
    missing = REQUIRED_COLS - set(df.columns)
    assert REQUIRED_COLS.issubset(set(df.columns)), f"Missing cols: {missing}"
    assert len(df) >= 120, f"Expected ≥120 rows, got {len(df)}"
    assert df["market"].iloc[0] == market


@pytest.mark.parametrize(
    "ticker,market",
    [
        ("AAPL", "NASDAQ"),
        ("005930", "KOSDAQ"),
    ],
)
def test_cache_hit(ticker, market):
    # Warm the cache
    get_ohlcv(ticker, market, period_days=365)
    t0 = time.monotonic()
    df2 = get_ohlcv(ticker, market, period_days=365)
    elapsed = time.monotonic() - t0
    assert not df2.empty
    # Cache hit should be much faster than a network call
    assert elapsed < 2.0, f"Cache hit took {elapsed:.2f}s — expected <2s"


def test_unknown_ticker_raises():
    with pytest.raises(ValueError, match="ticker not found"):
        get_ohlcv("ZZZZNOTREAL", "NASDAQ", period_days=365)
