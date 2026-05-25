"""Tests for batch screener service (T21)."""
from __future__ import annotations

import pytest


def _fake_score(ticker, market):
    """Return deterministic fake scores for testing."""
    scores = {
        ("AAPL", "NASDAQ"): 75.0,
        ("MSFT", "NASDAQ"): 65.0,
        ("NVDA", "NASDAQ"): 55.0,
        ("AMZN", "NASDAQ"): 40.0,
        ("BADTICKER", "NASDAQ"): None,  # simulate failure
    }
    return scores.get((ticker, market), 50.0)


@pytest.fixture()
def patched_screener(monkeypatch):
    """Patch _safe_score_ticker in screener to avoid real network calls."""
    import app.services.screener as s

    def _mock(ticker, market):
        score = _fake_score(ticker, market)
        if score is None:
            return None
        return {
            "ticker": ticker,
            "market": market,
            "composite": score,
            "factors": {
                "fundamental": score,
                "valuation": score,
                "supply_demand": None,
                "momentum": score,
                "macro": None,
                "risk": score,
            },
            "unavailable": ["supply_demand", "macro"],
            "renormalized": True,
            "last_close": 100.0,
            "as_of": "2024-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(s, "_safe_score_ticker", _mock)
    return s


def _tickers(*names):
    return [{"ticker": t, "market": "NASDAQ", "name": t} for t in names]


def test_run_screen_returns_sorted_results(patched_screener):
    tickers = _tickers("AAPL", "MSFT", "NVDA", "AMZN")
    results = patched_screener.run_screen(tickers)
    assert len(results) == 4
    scores = [r["composite"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_run_screen_skips_failed_ticker(patched_screener):
    tickers = _tickers("AAPL", "BADTICKER", "MSFT")
    results = patched_screener.run_screen(tickers)
    returned_tickers = {r["ticker"] for r in results}
    assert "BADTICKER" not in returned_tickers
    assert "AAPL" in returned_tickers
    assert "MSFT" in returned_tickers


def test_run_screen_min_composite_filter(patched_screener):
    tickers = _tickers("AAPL", "MSFT", "NVDA", "AMZN")
    results = patched_screener.run_screen(tickers, min_composite=60.0)
    assert all(r["composite"] >= 60.0 for r in results)
    returned = {r["ticker"] for r in results}
    assert "AAPL" in returned
    assert "MSFT" in returned
    assert "NVDA" not in returned
    assert "AMZN" not in returned


def test_run_screen_market_filter(patched_screener):
    import app.services.screener as s

    mixed = [
        {"ticker": "AAPL", "market": "NASDAQ", "name": "Apple"},
        {"ticker": "005930", "market": "KOSDAQ", "name": "Samsung"},
    ]
    results = s.run_screen(mixed, market_filter="NASDAQ")
    assert all(r["market"] == "NASDAQ" for r in results)


def test_run_screen_empty_universe(patched_screener):
    import app.services.screener as s
    results = s.run_screen([])
    assert results == []


def test_run_screen_name_attached(patched_screener):
    tickers = [{"ticker": "AAPL", "market": "NASDAQ", "name": "Apple Inc."}]
    results = patched_screener.run_screen(tickers)
    assert results[0]["name"] == "Apple Inc."
