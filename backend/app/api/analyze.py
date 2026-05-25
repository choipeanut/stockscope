"""GET /analyze?ticker=&market= — M2 full 6-factor composite."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

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
from app.scoring.scenarios import generate_scenarios
from app.scoring.supply_demand import compute_supply_demand
from app.scoring.valuation import compute_valuation

router = APIRouter()

_INDEX_TICKER: dict[str, str] = {
    "KOSDAQ": "^KQ11",
    "NASDAQ": "^IXIC",
}


def _get_index_df(market: str):
    try:
        return get_ohlcv(_INDEX_TICKER.get(market, "^IXIC"), market, period_days=365)
    except Exception:
        return None


def _s(val: Any) -> Any:
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _clean(d: dict) -> dict:
    return {k: _s(v) for k, v in d.items()}


def _score_or_none(score: float) -> float | None:
    return None if math.isnan(score) else score


@router.get("/analyze")
def analyze(
    ticker: str = Query(..., description="Ticker symbol"),
    market: str = Query(..., description="KOSDAQ or NASDAQ"),
    sector: str = Query("", description="Sector hint for macro modulation"),
) -> dict:
    market = market.upper()
    if market not in ("KOSDAQ", "NASDAQ"):
        raise HTTPException(status_code=400, detail="market must be KOSDAQ or NASDAQ")

    try:
        df = get_ohlcv(ticker, market, period_days=365)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"ticker not found: {ticker}")

    as_of = datetime.now(timezone.utc).isoformat()
    index_df = _get_index_df(market)

    # ── Compute all sub-scores ───────────────────────────────────────
    momentum_result = compute_momentum(df, index_df)

    val_data = get_valuation(ticker, market)
    val_result = compute_valuation(val_data)

    fund_data = get_fundamentals(ticker, market)
    fund_result = compute_fundamental(fund_data)

    flow_data = get_flows(ticker, market)
    sd_result = compute_supply_demand(flow_data)

    macro_data = get_macro(ticker, market)
    macro_result = compute_macro(macro_data, sector=sector)

    risk_data = get_risk(ticker, market, price_df=df, index_df=index_df)
    risk_result = compute_risk(risk_data, fund_data=fund_data)

    # ── Composite ────────────────────────────────────────────────────
    factor_scores: dict[str, float | None] = {
        "fundamental": _score_or_none(fund_result.score),
        "valuation": _score_or_none(val_result.score),
        "supply_demand": _score_or_none(sd_result.score),
        "momentum": _score_or_none(momentum_result.score),
        "macro": _score_or_none(macro_result.score),
        "risk": _score_or_none(risk_result.score),
    }

    composite_result = compute_composite(factor_scores, as_of=as_of)

    # ── Scenarios ────────────────────────────────────────────────────
    scenarios = generate_scenarios(
        factors=factor_scores,
        momentum_detail={"components": momentum_result.components},
        fund_data=fund_data,
        flow_data=flow_data,
        macro_data=macro_data,
        risk_data=risk_data,
    )

    # ── OHLCV ────────────────────────────────────────────────────────
    ohlcv_records = df.tail(365).copy()
    ohlcv_records["date"] = ohlcv_records["date"].astype(str)
    ohlcv_list = ohlcv_records[
        ["date", "open", "high", "low", "close", "volume"]
    ].to_dict(orient="records")

    # ── Collect key_required warnings ───────────────────────────────
    key_required = []
    if fund_data.get("key_required"):
        key_required.append(fund_data["key_required"])
    if macro_data.get("key_required"):
        key_required.extend(macro_data["key_required"])
    if risk_data.get("key_required"):
        key_required.append(risk_data["key_required"])

    return {
        "ticker": ticker,
        "market": market,
        "as_of": as_of,
        "composite": _s(composite_result.composite),
        "factors": _clean(composite_result.factors),
        "unavailable": composite_result.unavailable,
        "renormalized": composite_result.renormalized,
        "key_required": list(set(k for k in key_required if k)),
        "momentum_detail": {
            "components": _clean(momentum_result.components),
            "unavailable": momentum_result.unavailable,
        },
        "valuation_detail": _clean(val_result.components),
        "supply_demand_detail": {
            "components": _clean(sd_result.components),
            "proxy": sd_result.proxy,
        },
        "macro_detail": {
            "regime": macro_result.regime,
            "sector_hints": macro_result.sector_hints,
            "components": _clean(macro_result.components),
        },
        "risk_detail": {
            "penalties": risk_result.penalties,
            "partial": risk_result.partial,
            "components": _clean(risk_result.components),
        },
        "scenarios": [
            {
                "stance": s.stance,
                "probability_hint": s.probability_hint,
                "reasons": s.reasons,
                "watch_conditions": s.watch_conditions,
            }
            for s in scenarios
        ],
        "ohlcv": ohlcv_list,
        "notice": "Not investment advice. Scores are educational only.",
    }
