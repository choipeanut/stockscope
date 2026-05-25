"""Batch scoring service for the stock screener (T21)."""
from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app.collectors.flows import get_flows
from app.collectors.fundamentals import get_fundamentals
from app.collectors.macro import get_macro
from app.collectors.prices import get_ohlcv
from app.collectors.risk import get_risk
from app.collectors.valuation import get_valuation
from app.scoring.composite import compute_composite
from app.scoring.fundamental import compute_fundamental
from app.scoring.macro_score import compute_macro
from app.scoring.momentum import compute_momentum
from app.scoring.risk import compute_risk
from app.scoring.supply_demand import compute_supply_demand
from app.scoring.valuation import compute_valuation

logger = logging.getLogger(__name__)

_MAX_WORKERS = 6
_MIN_INTERVAL = 0.2  # seconds between requests per source

_INDEX_TICKER: dict[str, str] = {
    "KOSDAQ": "^KQ11",
    "NASDAQ": "^IXIC",
}

# Module-level index cache (shared across workers, computed once per run)
_index_cache: dict[str, Any] = {}


def _get_index_df(market: str):
    if market not in _index_cache:
        try:
            _index_cache[market] = get_ohlcv(
                _INDEX_TICKER.get(market, "^IXIC"), market, period_days=365
            )
        except Exception:
            _index_cache[market] = None
    return _index_cache[market]


def _score_or_none(score: float) -> float | None:
    if isinstance(score, float) and (math.isnan(score) or math.isinf(score)):
        return None
    return score


def _safe_score_ticker(ticker: str, market: str) -> dict | None:
    """Score a single ticker; returns None on unrecoverable failure."""
    try:
        df = get_ohlcv(ticker, market, period_days=365)
    except Exception as e:
        logger.debug("skip %s/%s: price fetch failed: %s", ticker, market, e)
        return None

    index_df = _get_index_df(market)
    as_of = datetime.now(timezone.utc).isoformat()

    try:
        momentum = compute_momentum(df, index_df)
    except Exception:
        momentum = None

    try:
        val_data = get_valuation(ticker, market)
        val_result = compute_valuation(val_data)
    except Exception:
        val_data, val_result = {}, None

    try:
        fund_data = get_fundamentals(ticker, market)
        fund_result = compute_fundamental(fund_data)
    except Exception:
        fund_data, fund_result = {}, None

    try:
        flow_data = get_flows(ticker, market)
        sd_result = compute_supply_demand(flow_data)
    except Exception:
        flow_data, sd_result = {}, None

    try:
        macro_data = get_macro(ticker, market)
        macro_result = compute_macro(macro_data)
    except Exception:
        macro_data, macro_result = {}, None

    try:
        risk_data = get_risk(ticker, market, price_df=df, index_df=index_df)
        risk_result = compute_risk(risk_data, fund_data=fund_data)
    except Exception:
        risk_data, risk_result = {}, None

    factor_scores: dict[str, float | None] = {
        "fundamental": _score_or_none(fund_result.score) if fund_result else None,
        "valuation": _score_or_none(val_result.score) if val_result else None,
        "supply_demand": _score_or_none(sd_result.score) if sd_result else None,
        "momentum": _score_or_none(momentum.score) if momentum else None,
        "macro": _score_or_none(macro_result.score) if macro_result else None,
        "risk": _score_or_none(risk_result.score) if risk_result else None,
    }

    composite = compute_composite(factor_scores, as_of=as_of)

    last_close = float(df["close"].iloc[-1]) if not df.empty else None

    return {
        "ticker": ticker,
        "market": market,
        "composite": _score_or_none(composite.composite),
        "factors": composite.factors,
        "unavailable": composite.unavailable,
        "renormalized": composite.renormalized,
        "last_close": last_close,
        "as_of": as_of,
    }


def _throttled_score(ticker: str, market: str, delay: float) -> dict | None:
    if delay > 0:
        time.sleep(delay)
    return _safe_score_ticker(ticker, market)


def run_screen(
    tickers: list[dict],
    min_composite: float = 0.0,
    market_filter: str | None = None,
) -> list[dict]:
    """
    Score all tickers concurrently (max _MAX_WORKERS threads) with throttling.

    Args:
        tickers: list of {ticker, market, name}
        min_composite: minimum composite score to include in results
        market_filter: optional "KOSDAQ" | "NASDAQ"

    Returns:
        list of scored dicts sorted by composite desc
    """
    _index_cache.clear()

    if market_filter:
        tickers = [t for t in tickers if t["market"].upper() == market_filter.upper()]

    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {}
        for i, item in enumerate(tickers):
            # Stagger submissions to respect per-source rate limits
            delay = (i // _MAX_WORKERS) * _MIN_INTERVAL
            f = pool.submit(_throttled_score, item["ticker"], item["market"], delay)
            futures[f] = item

        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as e:
                logger.warning("score failed for %s: %s", item["ticker"], e)
                result = None

            if result is None:
                continue
            if result["composite"] is None:
                continue
            if result["composite"] < min_composite:
                continue

            result["name"] = item.get("name", "")
            results.append(result)

    results.sort(key=lambda r: r["composite"] or 0, reverse=True)
    return results
