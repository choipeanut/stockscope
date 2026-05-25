"""Tests for paper trading service (T19)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "portfolio_test.db"


def _patch_db(monkeypatch, tmp_path):
    """Point repo._DB_PATH at a fresh temp DB for each test."""
    import app.db.repo as repo
    db_path = _make_tmp_db(tmp_path)
    monkeypatch.setattr(repo, "_DB_PATH", db_path)
    # Force account seed on first connection
    repo._conn().close()
    return db_path


def _patch_price(monkeypatch, price: float):
    """Patch _latest_price in paper_trading so it returns a fixed price."""
    import app.services.paper_trading as pt

    monkeypatch.setattr(pt, "_latest_price", lambda ticker, market: price)


def _patch_prices_seq(monkeypatch, prices: list[float]):
    """Return prices sequentially across multiple _latest_price calls."""
    import app.services.paper_trading as pt
    call = [0]

    def _fake(ticker, market):
        p = prices[min(call[0], len(prices) - 1)]
        call[0] += 1
        return p

    monkeypatch.setattr(pt, "_latest_price", _fake)


# ---------------------------------------------------------------------------
# Buy tests
# ---------------------------------------------------------------------------

def test_buy_deducts_cash(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy
    from app.db import repo

    buy("005930", "KOSDAQ", 10)

    acct = repo.get_account()
    assert acct["cash"] == pytest.approx(10_000_000 - 70_000 * 10)


def test_buy_creates_holding(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy
    from app.db import repo

    buy("005930", "KOSDAQ", 5)

    h = repo.get_holding("005930", "KOSDAQ")
    assert h is not None
    assert h["qty"] == pytest.approx(5)
    assert h["avg_price"] == pytest.approx(70_000.0)


def test_buy_avg_price_recomputed(monkeypatch, tmp_path):
    """Second buy at different price → weighted average recalculated."""
    _patch_db(monkeypatch, tmp_path)
    _patch_prices_seq(monkeypatch, [60_000.0, 80_000.0])

    from app.services.paper_trading import buy
    from app.db import repo

    buy("005930", "KOSDAQ", 10)   # @ 60k
    buy("005930", "KOSDAQ", 10)   # @ 80k

    h = repo.get_holding("005930", "KOSDAQ")
    expected_avg = (60_000 * 10 + 80_000 * 10) / 20
    assert h["avg_price"] == pytest.approx(expected_avg)
    assert h["qty"] == pytest.approx(20)


def test_buy_insufficient_cash(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, TradeError

    with pytest.raises(TradeError):
        buy("005930", "KOSDAQ", 1_000_000)


def test_buy_records_transaction(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 50_000.0)

    from app.services.paper_trading import buy
    from app.db import repo

    buy("005930", "KOSDAQ", 3)
    txs = repo.get_transactions()
    assert len(txs) == 1
    assert txs[0]["side"] == "BUY"
    assert txs[0]["qty"] == pytest.approx(3)
    assert txs[0]["price"] == pytest.approx(50_000.0)


# ---------------------------------------------------------------------------
# Sell tests
# ---------------------------------------------------------------------------

def test_sell_updates_holding(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, sell
    from app.db import repo

    buy("005930", "KOSDAQ", 10)
    sell("005930", "KOSDAQ", 4)

    h = repo.get_holding("005930", "KOSDAQ")
    assert h["qty"] == pytest.approx(6)


def test_sell_removes_holding_when_zero(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, sell
    from app.db import repo

    buy("005930", "KOSDAQ", 10)
    sell("005930", "KOSDAQ", 10)

    h = repo.get_holding("005930", "KOSDAQ")
    assert h is None


def test_sell_realized_pnl(monkeypatch, tmp_path):
    """Buy at 60k, sell at 70k → realized PnL = 10k × qty."""
    _patch_db(monkeypatch, tmp_path)
    _patch_prices_seq(monkeypatch, [60_000.0, 70_000.0])

    from app.services.paper_trading import buy, sell

    buy("005930", "KOSDAQ", 5)    # @ 60k
    result = sell("005930", "KOSDAQ", 5)  # @ 70k

    assert result["realized_pnl"] == pytest.approx(10_000 * 5)


def test_sell_no_holding(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import sell, TradeError

    with pytest.raises(TradeError):
        sell("005930", "KOSDAQ", 1)


def test_sell_excess_qty(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, sell, TradeError

    buy("005930", "KOSDAQ", 5)
    with pytest.raises(TradeError):
        sell("005930", "KOSDAQ", 10)


def test_sell_adds_cash(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, sell
    from app.db import repo

    buy("005930", "KOSDAQ", 10)
    cash_after_buy = repo.get_account()["cash"]
    sell("005930", "KOSDAQ", 10)
    cash_after_sell = repo.get_account()["cash"]

    assert cash_after_sell == pytest.approx(cash_after_buy + 70_000 * 10)


# ---------------------------------------------------------------------------
# Portfolio snapshot tests
# ---------------------------------------------------------------------------

def test_get_portfolio_totals(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import buy, get_portfolio

    buy("005930", "KOSDAQ", 10)
    pf = get_portfolio()

    expected_cash = 10_000_000 - 70_000 * 10
    assert pf["cash"] == pytest.approx(expected_cash)
    assert len(pf["holdings"]) == 1

    h = pf["holdings"][0]
    assert h["ticker"] == "005930"
    assert h["qty"] == pytest.approx(10)
    assert h["current_price"] == pytest.approx(70_000.0)
    assert h["position_value"] == pytest.approx(70_000 * 10)
    assert h["unrealized_pnl"] == pytest.approx(0.0)
    assert pf["totals"]["total_assets"] == pytest.approx(10_000_000.0)


def test_get_portfolio_empty(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    _patch_price(monkeypatch, 70_000.0)

    from app.services.paper_trading import get_portfolio

    pf = get_portfolio()
    assert pf["cash"] == pytest.approx(10_000_000.0)
    assert pf["holdings"] == []
    assert pf["totals"]["positions_value"] == pytest.approx(0.0)
    assert pf["totals"]["total_assets"] == pytest.approx(10_000_000.0)
