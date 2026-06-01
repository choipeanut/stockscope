"""Tests for the Phase-0 point-in-time backtest engine.

These use synthetic, deterministic OHLCV (no network) and verify:
  1. point-in-time slicing never leaks the future,
  2. forward returns are measured after the decision date,
  3. a constructed "momentum predicts returns" world yields positive IC,
  4. the engine degrades gracefully with too few tickers.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.backtest import engine


def _make_df(start: date, closes: list[float], market: str = "NASDAQ") -> pd.DataFrame:
    rows = []
    d = start
    for c in closes:
        rows.append({
            "date": d, "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1_000_000, "market": market,
        })
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def test_slice_up_to_excludes_future():
    df = _make_df(date(2020, 1, 1), [10, 11, 12, 13, 14])
    sl = engine._slice_up_to(df, date(2020, 1, 3))
    assert sl["date"].max() == date(2020, 1, 3)
    assert len(sl) == 3  # no future rows leaked


def test_forward_return_is_after_as_of():
    df = _make_df(date(2020, 1, 1), [100, 101, 102, 103, 110])
    # entry = close at as_of (idx 1 -> 101); exit 2 trading rows later -> 110
    fr = engine._forward_return(df, date(2020, 1, 2), holding_days=3)
    assert fr == 110 / 101 - 1.0


def test_spearman_monotonic():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
    assert engine._spearman(a, b) == pytest.approx(1.0)


def test_momentum_predicts_returns_positive_ic(monkeypatch):
    """Construct a world where higher momentum -> higher forward return.

    Each ticker has a constant daily drift; stronger drift means both a higher
    momentum score (rising trend) AND higher forward returns. A correct
    point-in-time engine should detect positive IC.
    """
    n_days = 400
    start = date(2020, 1, 1)
    drifts = {
        "AAA": 0.0015, "BBB": 0.0010, "CCC": 0.0005,
        "DDD": 0.0000, "EEE": -0.0005, "FFF": -0.0010,
    }
    price_map = {}
    for t, dft in drifts.items():
        closes = [100 * (1 + dft) ** i for i in range(n_days)]
        price_map[(t, "NASDAQ")] = _make_df(start, closes)

    universe = [{"ticker": t, "market": "NASDAQ", "name": t} for t in drifts]

    monkeypatch.setattr(engine, "get_universe", lambda m=None: universe)
    monkeypatch.setattr(engine, "_load_prices", lambda tickers, lb: price_map)
    monkeypatch.setattr(engine, "_load_index", lambda market, lb: None)

    result = engine.run_backtest(
        market="NASDAQ", factor="momentum", years=1.0,
        rebalance_days=21, holding_days=21, n_quantiles=3,
    )

    assert result.n_rebalances > 0
    assert result.mean_ic is not None
    # higher momentum -> higher forward return by construction
    assert result.mean_ic > 0.3
    assert result.mean_long_short > 0


def test_graceful_with_no_data(monkeypatch):
    monkeypatch.setattr(engine, "get_universe", lambda m=None: [])
    monkeypatch.setattr(engine, "_load_prices", lambda tickers, lb: {})
    monkeypatch.setattr(engine, "_load_index", lambda market, lb: None)

    result = engine.run_backtest(market="NASDAQ", years=1.0)
    assert result.n_rebalances == 0
    assert result.mean_ic is None
    assert result.warnings
