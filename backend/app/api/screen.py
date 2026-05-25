"""GET /screen — batch screener endpoint.

Design: synchronous with hard wall-clock timeout via concurrent.futures.wait().
socket.setdefaulttimeout() prevents yfinance from hanging forever.
Results cached in-process for 30 minutes.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait as cf_wait
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.collectors.universe import get_universe
from app.services.screener import _safe_score_ticker  # reuse per-ticker logic

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL = 1800  # 30분
_WALL_TIMEOUT = 55  # 초 — wall-clock 최대 대기 (Render HTTP 제한 고려)

_last_result: dict | None = None
_last_run_at: float = 0.0  # time.time()
_running = False


@router.get("/screen")
def screen(
    market: str = Query("", description="Filter: KOSDAQ | NASDAQ | (empty = both)"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=200),
    refresh: bool = Query(False, description="강제 새로고침"),
) -> dict:
    global _last_result, _last_run_at, _running

    market_filter = market.upper() if market else None

    # 캐시 유효하면 즉시 반환
    cache_valid = (
        _last_result is not None
        and not refresh
        and (time.time() - _last_run_at) < _CACHE_TTL
    )
    if cache_valid:
        return _build_response(_last_result, min_score, limit, stale=False)

    # 이미 동기 실행 중이면 이전 캐시 반환 (없으면 빈 결과)
    if _running:
        if _last_result:
            return _build_response(_last_result, min_score, limit, stale=True)
        return {"status": "running", "results": [], "total": 0, "stale": True, "error": None}

    _running = True
    logger.info("[screener] starting synchronous run (market=%s)", market_filter)

    try:
        results = _run_sync(market_filter)
        _last_result = {"results": results, "market": market_filter}
        _last_run_at = time.time()
        logger.info("[screener] done: %d results", len(results))
    except Exception as e:
        logger.exception("[screener] unexpected error: %s", e)
        results = []
    finally:
        _running = False

    if _last_result:
        return _build_response(_last_result, min_score, limit, stale=False)
    return {"status": "ok", "results": [], "total": 0, "stale": False, "error": "분석 실패 — 잠시 후 다시 시도하세요"}


def _run_sync(market_filter: str | None) -> list[dict]:
    """wall-clock 제한 안에서 종목 스코어링.

    소켓 타임아웃을 쓰지 않음 — Render cold-start에서 yfinance가 12s를 초과할 수 있음.
    대신 cf_wait(timeout) 로 wall-clock 한도를 지키고,
    pool.shutdown(wait=False) 로 미완료 스레드를 블록 없이 해제.
    """
    tickers = get_universe(market_filter)
    logger.info("[screener] universe: %d tickers", len(tickers))

    results: list[dict] = []
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        future_map = {
            pool.submit(_safe_score_ticker, item["ticker"], item["market"]): item
            for item in tickers
        }
        # wall-clock 타임아웃: 완료된 것만 수집
        done, not_done = cf_wait(future_map.keys(), timeout=_WALL_TIMEOUT)

        if not_done:
            logger.warning(
                "[screener] %d/%d tickers timed out after %ds",
                len(not_done), len(tickers), _WALL_TIMEOUT,
            )

        for fut in done:
            item = future_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                logger.debug("[screener] %s failed: %s", item["ticker"], e)
                result = None

            if result is None or result.get("composite") is None:
                continue

            result["name"] = item.get("name", "")
            results.append(result)
    finally:
        # 미완료 스레드를 기다리지 않고 즉시 응답 반환
        pool.shutdown(wait=False)

    results.sort(key=lambda r: r.get("composite") or 0, reverse=True)
    return results


@router.get("/screen/debug-score")
def debug_score(ticker: str = "AAPL", market: str = "NASDAQ") -> dict:
    """단일 종목 스코어링 디버그 — 각 단계별 성공/실패 반환."""
    import traceback

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

    steps: dict = {}

    try:
        df = get_ohlcv(ticker, market, period_days=365)
        steps["ohlcv"] = f"ok ({len(df)} rows, last={df['close'].iloc[-1]:.2f})"
    except Exception as e:
        steps["ohlcv"] = f"FAIL: {e}"
        return {"ticker": ticker, "market": market, "steps": steps, "composite": None}

    index_ticker = "^IXIC" if market == "NASDAQ" else "^KQ11"
    try:
        index_df = get_ohlcv(index_ticker, market, period_days=365)
        steps["index"] = "ok"
    except Exception as e:
        index_df = None
        steps["index"] = f"FAIL: {e}"

    factor_scores: dict = {}

    try:
        m = compute_momentum(df, index_df)
        factor_scores["momentum"] = round(m.score, 2)
        steps["momentum"] = "ok"
    except Exception as e:
        factor_scores["momentum"] = None
        steps["momentum"] = f"FAIL: {e}"

    try:
        val_data = get_valuation(ticker, market)
        val_result = compute_valuation(val_data)
        factor_scores["valuation"] = round(val_result.score, 2)
        steps["valuation"] = f"ok (per={val_data.get('per')}, pbr={val_data.get('pbr')})"
    except Exception as e:
        factor_scores["valuation"] = None
        steps["valuation"] = f"FAIL: {e}"

    try:
        fund_data = get_fundamentals(ticker, market)
        fund_result = compute_fundamental(fund_data)
        factor_scores["fundamental"] = round(fund_result.score, 2)
        steps["fundamental"] = f"ok (revenue_growth={fund_data.get('revenue_growth')})"
    except Exception as e:
        factor_scores["fundamental"] = None
        steps["fundamental"] = f"FAIL: {e}"

    try:
        flow_data = get_flows(ticker, market)
        sd_result = compute_supply_demand(flow_data)
        factor_scores["supply_demand"] = round(sd_result.score, 2)
        steps["supply_demand"] = "ok"
    except Exception as e:
        factor_scores["supply_demand"] = None
        steps["supply_demand"] = f"FAIL: {e}"

    try:
        macro_data = get_macro(ticker, market)
        macro_result = compute_macro(macro_data)
        factor_scores["macro"] = round(macro_result.score, 2)
        steps["macro"] = "ok"
    except Exception as e:
        factor_scores["macro"] = None
        steps["macro"] = f"FAIL: {e}"

    try:
        risk_data = get_risk(ticker, market, price_df=df, index_df=index_df)
        fund_d = {} if factor_scores.get("fundamental") is None else {"available": True}
        risk_result = compute_risk(risk_data, fund_data=fund_d)
        factor_scores["risk"] = round(risk_result.score, 2)
        steps["risk"] = "ok"
    except Exception as e:
        factor_scores["risk"] = None
        steps["risk"] = f"FAIL: {e}"

    from datetime import datetime, timezone
    composite = compute_composite(factor_scores, as_of=datetime.now(timezone.utc).isoformat())
    steps["composite"] = composite.composite

    return {
        "ticker": ticker,
        "market": market,
        "steps": steps,
        "factor_scores": factor_scores,
        "composite": composite.composite,
        "unavailable": composite.unavailable,
    }


@router.get("/screen/status")
def screen_status() -> dict:
    return {
        "running": _running,
        "has_result": _last_result is not None,
        "result_count": len(_last_result.get("results", [])) if _last_result else 0,
        "last_run_at": datetime.fromtimestamp(_last_run_at, tz=timezone.utc).isoformat() if _last_run_at else None,
        "cache_age_sec": round(time.time() - _last_run_at) if _last_run_at else None,
    }


def _build_response(cache: dict, min_score: float, limit: int, stale: bool) -> dict:
    results = cache.get("results", [])
    filtered = [r for r in results if (r.get("composite") or 0) >= min_score]
    return {
        "status": "ok",
        "stale": stale,
        "total": len(filtered),
        "results": filtered[:limit],
        "as_of": datetime.fromtimestamp(_last_run_at, tz=timezone.utc).isoformat() if _last_run_at else None,
        "error": None,
    }
