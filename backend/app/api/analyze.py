"""GET /analyze?ticker=&market= — 7-factor composite (+ market_sentiment)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.collectors.analyst import get_analyst_data
from app.collectors.company_name import get_company_name
from app.collectors.flows import get_flows
from app.collectors.fundamentals import get_fundamentals
from app.collectors.insider import get_insider_data
from app.collectors.macro import get_macro
from app.collectors.news import get_news
from app.collectors.news_macro import get_global_market_news
from app.collectors.options_data import get_options_data
from app.collectors.prices import get_ohlcv
from app.collectors.risk import get_risk
from app.collectors.valuation import get_valuation
from app.scoring.analyst import compute_analyst
from app.scoring.composite import compute_composite
from app.scoring.fundamental import compute_fundamental
from app.scoring.insider import compute_insider
from app.scoring.macro_score import compute_macro
from app.scoring.momentum import compute_momentum
from app.scoring.options_score import compute_options
from app.scoring.risk import compute_risk
from app.scoring.scenarios import generate_scenarios
from app.scoring.supply_demand import compute_supply_demand
from app.scoring.valuation import compute_valuation
from app.services.macro_sentiment import analyze_market_sentiment

router = APIRouter()

_INDEX_TICKER: dict[str, str] = {
    "KOSPI":  "^KS11",
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
    if market not in ("KOSPI", "KOSDAQ", "NASDAQ"):
        raise HTTPException(status_code=400, detail="market must be KOSPI, KOSDAQ or NASDAQ")

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

    # ── Market Sentiment (global macro news → factor) ────────────────
    global_news = get_global_market_news(limit_per_category=4)
    market_sentiment_data = analyze_market_sentiment(global_news)
    market_sentiment_score: float | None = (
        float(market_sentiment_data["market_score"])
        if market_sentiment_data.get("available")
        else None
    )

    # ── Analyst Consensus ────────────────────────────────────────────
    analyst_data = get_analyst_data(ticker, market)
    analyst_result = compute_analyst(analyst_data)

    # ── Insider Trading ──────────────────────────────────────────────
    insider_data = get_insider_data(ticker, market)
    insider_result = compute_insider(insider_data)

    # ── Options Market ───────────────────────────────────────────────
    options_data = get_options_data(ticker, market)
    options_result = compute_options(options_data)

    # ── Composite ────────────────────────────────────────────────────
    factor_scores: dict[str, float | None] = {
        "fundamental":      _score_or_none(fund_result.score),
        "valuation":        _score_or_none(val_result.score),
        "supply_demand":    _score_or_none(sd_result.score),
        "momentum":         _score_or_none(momentum_result.score),
        "macro":            _score_or_none(macro_result.score),
        "risk":             _score_or_none(risk_result.score),
        "market_sentiment": market_sentiment_score,
        "analyst":          _score_or_none(analyst_result.score),
        "insider":          _score_or_none(insider_result.score),
        "options":          _score_or_none(options_result.score),
    }

    composite_result = compute_composite(factor_scores, as_of=as_of)

    # ── News & Sentiment ─────────────────────────────────────────────
    try:
        news_data = get_news(ticker, market, limit=10)
        sentiment = news_data.get("sentiment", {})
        delta = int(sentiment.get("score_delta", 0)) if sentiment.get("available") else 0
    except Exception:
        news_data = {"news": [], "disclosures": [], "sentiment": {}}
        sentiment = {}
        delta = 0

    raw_composite = composite_result.composite
    adjusted_composite = (
        None if raw_composite is None
        else max(0.0, min(100.0, raw_composite + delta))
    )

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

    company_name = get_company_name(ticker, market)

    return {
        "ticker": ticker,
        "market": market,
        "name": company_name,
        "as_of": as_of,
        "composite": _s(adjusted_composite),
        "composite_raw": _s(raw_composite),
        "sentiment_delta": delta,
        "sentiment": sentiment,
        "factors": _clean(composite_result.factors),
        "unavailable": composite_result.unavailable,
        "renormalized": composite_result.renormalized,
        "key_required": list(set(k for k in key_required if k)),
        "momentum_detail": {
            "components": _clean(momentum_result.components),
            "unavailable": momentum_result.unavailable,
        },
        "valuation_detail": _clean(val_data),  # 실제 PER/PBR/PSR 수치 (점수 아님)
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
        "market_sentiment_detail": {
            "market_score": market_sentiment_data.get("market_score"),
            "market_trend": market_sentiment_data.get("market_trend"),
            "confidence": market_sentiment_data.get("confidence"),
            "summary": market_sentiment_data.get("summary"),
            "key_themes": market_sentiment_data.get("key_themes", []),
            "available": market_sentiment_data.get("available", False),
        },
        "analyst_detail": {
            "mean_target":   _s(analyst_data.get("mean_target")),
            "current_price": _s(analyst_data.get("current_price")),
            "upside_pct":    _s(analyst_data.get("upside_pct")),
            "strong_buy":    analyst_data.get("strong_buy", 0),
            "buy":           analyst_data.get("buy", 0),
            "hold":          analyst_data.get("hold", 0),
            "sell":          analyst_data.get("sell", 0),
            "strong_sell":   analyst_data.get("strong_sell", 0),
            "num_analysts":  analyst_data.get("num_analysts", 0),
            "upgrades_3m":   analyst_data.get("upgrades_3m", 0),
            "downgrades_3m": analyst_data.get("downgrades_3m", 0),
            "available":     analyst_data.get("available", False),
            "components":    _clean(analyst_result.components),
        },
        "insider_detail": {
            "buy_count":  insider_data.get("buy_count", 0),
            "sell_count": insider_data.get("sell_count", 0),
            "buy_value":  _s(insider_data.get("buy_value")),
            "sell_value": _s(insider_data.get("sell_value")),
            "net_value":  _s(insider_data.get("net_value")),
            "available":  insider_data.get("available", False),
            "components": _clean(insider_result.components),
        },
        "options_detail": {
            "put_call_volume_ratio": _s(options_data.get("put_call_volume_ratio")),
            "put_call_oi_ratio":     _s(options_data.get("put_call_oi_ratio")),
            "avg_iv":                _s(options_data.get("avg_iv")),
            "call_volume":           options_data.get("call_volume", 0),
            "put_volume":            options_data.get("put_volume", 0),
            "available":             options_data.get("available", False),
            "components":            _clean(options_result.components),
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
