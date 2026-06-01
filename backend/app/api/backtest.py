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

# Shared point-in-time dataset cache, keyed by (market, years, rebalance, holding).
# Both /predict and /predict/eval build the SAME dataset; caching it here avoids
# re-fetching multi-year OHLCV for the whole universe twice (the cause of the
# /predict timeout on small servers).
_DATASET_CACHE: dict[str, tuple[float, object]] = {}


def _get_dataset(market_filter, years, rebalance_days, holding_days):
    """Build (or reuse) the point-in-time dataset for these parameters."""
    from app.backtest.dataset import build_dataset

    key = f"ds:{market_filter}:{years}:{rebalance_days}:{holding_days}"
    cached = _DATASET_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]
    df = build_dataset(
        market=market_filter, years=years,
        rebalance_days=rebalance_days, holding_days=holding_days,
    )
    _DATASET_CACHE[key] = (time.time(), df)
    return df


def _build_eval(market_filter, years, rebalance_days, holding_days, n_splits):
    """Build dataset + walk-forward report (imported lazily to keep import cheap)."""
    from app.backtest.model import walk_forward_eval

    df = _get_dataset(market_filter, years, rebalance_days, holding_days)
    report = walk_forward_eval(df, n_splits=n_splits)
    return df, report


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


@router.get("/predict/eval")
def predict_eval(
    market: str = Query("", description="KOSDAQ | NASDAQ | (empty = both)"),
    years: float = Query(5.0, ge=1.0, le=10.0),
    rebalance_days: int = Query(21, ge=5, le=120),
    holding_days: int = Query(21, ge=5, le=120),
    n_splits: int = Query(4, ge=1, le=10),
) -> dict:
    """Walk-forward, out-of-sample evaluation of the prediction model.

    Answers: does the trained model beat chance on data it never saw?
    """
    from dataclasses import asdict as _asdict

    market_filter = market.upper() if market else None
    key = f"eval:{market_filter}:{years}:{rebalance_days}:{holding_days}:{n_splits}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return {**cached[1], "cached": True}

    df, report = _build_eval(market_filter, years, rebalance_days, holding_days, n_splits)
    payload = {
        "market": market_filter or "ALL",
        "n_samples": int(len(df)),
        "report": _asdict(report),
    }
    _CACHE[key] = (time.time(), payload)
    return {**payload, "cached": False}


@router.get("/predict")
def predict(
    market: str = Query("", description="KOSDAQ | NASDAQ | (empty = both)"),
    years: float = Query(5.0, ge=1.0, le=10.0),
    holding_days: int = Query(21, ge=5, le=120),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Train on all history, then rank the CURRENT universe by predicted
    probability of beating the cross-section over the next `holding_days`.

    Output probabilities are honest model estimates, not guarantees — see the
    /predict/eval endpoint for the model's true out-of-sample skill.
    """
    from datetime import datetime, timezone

    from app.backtest.dataset import _features_at
    from app.backtest.engine import (
        _load_index,
        _load_prices,
        _slice_up_to,
    )
    from app.backtest.model import train_logistic
    from app.collectors.company_name import get_company_name
    from app.collectors.universe import get_universe

    market_filter = market.upper() if market else None

    # 1) train on the full point-in-time dataset (shared cache → no double build)
    df = _get_dataset(market_filter, years, 21, holding_days)
    if df.empty or df["label"].nunique() < 2:
        return {"status": "insufficient_data", "predictions": [], "as_of": None}
    model = train_logistic(df)

    # 2) score the CURRENT universe (features as of today)
    lookback_days = int(years * 365) + 200
    tickers = get_universe(market_filter)
    price_map = _load_prices(tickers, lookback_days)
    markets = {m for (_, m) in price_map}
    index_map = {m: _load_index(m, lookback_days) for m in markets}

    preds: list[dict] = []
    for (t, m), pdf in price_map.items():
        idx = index_map.get(m)
        feats = _features_at(_slice_up_to(pdf, pdf["date"].max()),
                             _slice_up_to(idx, idx["date"].max()) if idx is not None else None)
        if feats is None:
            continue
        import pandas as pd
        prob = float(model.predict_proba(pd.DataFrame([feats]))[0])
        name = next((i.get("name", "") for i in tickers if i["ticker"] == t), "")
        name = name or get_company_name(t, m)
        preds.append({
            "ticker": t, "market": m, "name": name,
            "probability": round(prob, 4),
            "features": {k: round(v, 2) for k, v in feats.items()},
        })

    preds.sort(key=lambda r: r["probability"], reverse=True)
    return {
        "status": "ok",
        "market": market_filter or "ALL",
        "horizon_days": holding_days,
        "n_train_samples": int(len(df)),
        "predictions": preds[:limit],
        "as_of": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "확률은 모델 추정치이며 투자 권유가 아닙니다. 실제 예측력은 /predict/eval 참조."
        ),
    }
