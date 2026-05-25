"""Tests for universe loader (T20)."""
from __future__ import annotations

from app.collectors.universe import get_kosdaq_universe, get_nasdaq_universe, get_universe


def test_nasdaq_universe_returns_list():
    rows = get_nasdaq_universe()
    assert isinstance(rows, list)
    assert len(rows) >= 10


def test_nasdaq_universe_has_required_keys():
    rows = get_nasdaq_universe()
    for row in rows:
        assert "ticker" in row
        assert "market" in row
        assert row["market"] == "NASDAQ"
        assert row["ticker"]  # non-empty


def test_nasdaq_contains_known_tickers():
    tickers = {r["ticker"] for r in get_nasdaq_universe()}
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_kosdaq_universe_returns_list():
    rows = get_kosdaq_universe()
    assert isinstance(rows, list)
    assert len(rows) >= 10


def test_kosdaq_universe_has_required_keys():
    rows = get_kosdaq_universe()
    for row in rows:
        assert "ticker" in row
        assert "market" in row
        assert row["market"] == "KOSDAQ"
        assert row["ticker"]


def test_get_universe_combined():
    rows = get_universe()
    markets = {r["market"] for r in rows}
    assert "KOSDAQ" in markets
    assert "NASDAQ" in markets


def test_get_universe_market_filter_kosdaq():
    rows = get_universe("KOSDAQ")
    assert all(r["market"] == "KOSDAQ" for r in rows)


def test_get_universe_market_filter_nasdaq():
    rows = get_universe("NASDAQ")
    assert all(r["market"] == "NASDAQ" for r in rows)
