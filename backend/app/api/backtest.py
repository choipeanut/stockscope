"""GET /backtest — point-in-time factor backtest (Phase 0).

Validates whether the factor score actually predicts forward returns, using
walk-forward evaluation with no future leakage. Runs synchronously but can be
slow on cold cache (fetches multi-year OHLCV for the whole universe), so a
short in-memory cache is applied per parameter set.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Query

from app.backtest.engine import run_backtest

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600  # 1 hour — backtests are expensive and don't change intraday


@router.get("/backtest")
def backtest(
    market: str = Query("", description="KOSDAQ | NASDAQ | (empty = both)"),
    factor: str = Query("momentum", description="point-in-time factor to test"),
    years: float = Query(3.0, ge=0.5, le=10.0),
    rebalance_days: int = Query(21, ge=5, le=120),
    holding_days: int = Query(21, ge=5, le=120),
    n_quantiles: int = Query(5, ge=2, le=10),
) -> dict:
    market_filter = market.upper() if market else None
    key = f"{market_filter}:{factor}:{years}:{rebalance_days}:{holding_days}:{n_quantiles}"

    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return {**cached[1], "cached": True}

    result = run_backtest(
        market=market_filter,
        factor=factor,
        years=years,
        rebalance_days=rebalance_days,
        holding_days=holding_days,
        n_quantiles=n_quantiles,
    )
    payload = asdict(result)
    _CACHE[key] = (time.time(), payload)
    return {**payload, "cached": False}
