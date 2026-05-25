"""T3 verify: Momentum sub-score on fixture and real data."""
import numpy as np
import pandas as pd
import pytest

from app.scoring.momentum import WEIGHTS, MomentumResult, compute_momentum


def _make_fixture(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """Synthetic price series for deterministic tests."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    if trend == "up":
        close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    elif trend == "down":
        close = 200 - np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    else:
        close = 150 + np.random.randn(n) * 2
    volume = 1_000_000 + np.random.randint(-200_000, 200_000, n)
    return pd.DataFrame(
        {"date": dates.date, "open": close * 0.99, "high": close * 1.01,
         "low": close * 0.98, "close": close, "volume": volume, "market": "NASDAQ"}
    )


def test_score_range():
    df = _make_fixture(200, "up")
    result = compute_momentum(df)
    assert isinstance(result, MomentumResult)
    assert 0 <= result.score <= 100


def test_bull_trend_scores_higher_than_bear():
    bull = compute_momentum(_make_fixture(200, "up"))
    bear = compute_momentum(_make_fixture(200, "down"))
    assert bull.score > bear.score, f"Bull {bull.score:.1f} should exceed bear {bear.score:.1f}"


def test_components_present():
    df = _make_fixture(200, "up")
    result = compute_momentum(df)
    assert len(result.components) > 0
    for v in result.components.values():
        assert 0 <= v <= 100


def test_insufficient_data_marks_unavailable():
    df = _make_fixture(50, "up")  # < 120 rows
    result = compute_momentum(df)
    # trend_alignment needs 120 rows
    assert "trend_alignment" in result.unavailable


def test_weights_sum_to_one():
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_renormalization_on_partial_data():
    """With only 60 rows, some components are unavailable; score must still be 0-100."""
    df = _make_fixture(80, "up")
    result = compute_momentum(df)
    assert not np.isnan(result.score)
    assert 0 <= result.score <= 100
    assert len(result.unavailable) > 0


@pytest.mark.parametrize("ticker,market", [("AAPL", "NASDAQ"), ("005930", "KOSDAQ")])
def test_real_ticker(ticker, market):
    from app.collectors.prices import get_ohlcv

    df = get_ohlcv(ticker, market, period_days=365)
    result = compute_momentum(df)
    assert 0 <= result.score <= 100
