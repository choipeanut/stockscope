"""GET /screen — batch screener endpoint.

Design: background thread로 전체 종목 스코어링, 결과 30분 캐시.
- 첫 요청: 백그라운드 시작 → 즉시 {status:"running"} 반환
- 이후 요청: 캐시에서 즉시 반환 (30분 유효)
- 백그라운드는 5분 wall-timeout (동기 HTTP와 무관)

yfinance 20초 HTTP 타임아웃 + KOSDAQ .KS 폴백으로 모든 종목 완료 가능.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as cf_wait
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.collectors.company_name import get_company_name
from app.collectors.universe import get_universe
from app.services.screener import _safe_score_ticker

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL = 1800          # 30분 캐시
_WALL_TIMEOUT = 300        # 백그라운드 최대 5분 (모든 종목 커버)
_MAX_WORKERS = 2         # 동시 OHLCV+펀더멘털 로드 제한 (512MB 메모리 피크 억제)

_last_result: dict | None = None
_last_run_at: float = 0.0
_running = False
_bg_thread: threading.Thread | None = None


def _run_background(market_filter: str | None) -> None:
    """Serialised against predict/catalyst via heavy_slot so concurrent heavy
    jobs can't stack their memory peaks past the 512MB limit (which surfaces on
    the client as a dropped connection / "network error")."""
    from app.services.heavy import heavy_slot
    try:
        # drop_caches: free any retained predict dataset panel before we spike —
        # the screener doesn't need it, and a resident panel is what tips a
        # screener-only run over 512MB.
        with heavy_slot(drop_caches=True):
            _run_background_inner(market_filter)
    except Exception as e:
        global _running
        logger.warning("[screener] background failed: %s", e, exc_info=True)
        _running = False


def _run_background_inner(market_filter: str | None) -> None:
    global _last_result, _last_run_at, _running
    logger.info("[screener] background start (market=%s)", market_filter)

    tickers = get_universe(market_filter)
    logger.info("[screener] universe: %d tickers", len(tickers))

    results: list[dict] = []
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        future_map = {
            # 365일치 OHLCV — analyze와 동일 기간으로 점수 일관성 확보
            pool.submit(_safe_score_ticker, item["ticker"], item["market"], 365): item
            for item in tickers
        }
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

            # universe name 우선, 없으면 yfinance 조회 (NASDAQ)
            result["name"] = item.get("name", "") or get_company_name(item["ticker"], item["market"])
            results.append(result)
    finally:
        pool.shutdown(wait=False)

    import gc
    gc.collect()
    results.sort(key=lambda r: r.get("composite") or 0, reverse=True)

    _last_result = {"results": results, "market": market_filter}
    _last_run_at = time.time()
    _running = False
    logger.info("[screener] background done: %d results", len(results))


@router.get("/screen")
def screen(
    market: str = Query("", description="Filter: KOSDAQ | NASDAQ | (empty = both)"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=200),
    refresh: bool = Query(False, description="강제 새로고침"),
) -> dict:
    global _last_result, _last_run_at, _running, _bg_thread

    market_filter = market.upper() if market else None

    # 캐시 유효하면 즉시 반환
    cache_valid = (
        _last_result is not None
        and not refresh
        and (time.time() - _last_run_at) < _CACHE_TTL
    )
    if cache_valid:
        return _build_response(_last_result, min_score, limit, stale=False)

    # 백그라운드가 이미 실행 중이면 stale 결과 반환
    if _running:
        if _last_result:
            return _build_response(_last_result, min_score, limit, stale=True)
        return {
            "status": "running",
            "results": [],
            "total": 0,
            "stale": True,
            "error": None,
            "as_of": None,
        }

    # 백그라운드 스코어링 시작
    _running = True
    _bg_thread = threading.Thread(
        target=_run_background,
        args=(market_filter,),
        daemon=True,
        name="screener-bg",
    )
    _bg_thread.start()
    logger.info("[screener] background thread launched")

    # 즉시 stale 결과 반환 (없으면 running 상태)
    if _last_result:
        return _build_response(_last_result, min_score, limit, stale=True)
    return {
        "status": "running",
        "message": "스코어링 시작됨 — 첫 로드는 1~3분 소요. 잠시 후 새로고침하세요.",
        "results": [],
        "total": 0,
        "stale": True,
        "error": None,
        "as_of": None,
    }


@router.get("/screen/debug-score")
def debug_score(ticker: str = "AAPL", market: str = "NASDAQ") -> dict:
    """단일 종목 스코어링 디버그 — 각 단계별 성공/실패 반환."""
    from datetime import datetime, timezone

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
        df = get_ohlcv(ticker, market, period_days=90)
        steps["ohlcv"] = f"ok ({len(df)} rows, last={df['close'].iloc[-1]:.2f})"
    except Exception as e:
        steps["ohlcv"] = f"FAIL: {e}"
        return {"ticker": ticker, "market": market, "steps": steps, "composite": None}

    _index_map = {"NASDAQ": "^IXIC", "KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    index_ticker = _index_map.get(market.upper(), "^KQ11")
    try:
        index_df = get_ohlcv(index_ticker, market, period_days=90)
        steps["index"] = "ok"
    except Exception as e:
        index_df = None
        steps["index"] = f"FAIL: {e}"

    factor_scores: dict = {}

    for name, fn_args in [
        ("momentum", lambda: compute_momentum(df, index_df)),
        ("valuation", lambda: compute_valuation(get_valuation(ticker, market))),
        ("fundamental", lambda: compute_fundamental(get_fundamentals(ticker, market))),
        ("supply_demand", lambda: compute_supply_demand(get_flows(ticker, market))),
        ("macro", lambda: compute_macro(get_macro(ticker, market))),
        ("risk", lambda: compute_risk(get_risk(ticker, market, price_df=df, index_df=index_df), fund_data={})),
    ]:
        try:
            r = fn_args()
            factor_scores[name] = round(r.score, 2)
            steps[name] = "ok"
        except Exception as e:
            factor_scores[name] = None
            steps[name] = f"FAIL: {e}"

    try:
        from app.collectors.news_macro import get_global_market_news
        from app.services.macro_sentiment import analyze_market_sentiment
        ms = analyze_market_sentiment(get_global_market_news(limit_per_category=4))
        factor_scores["market_sentiment"] = float(ms["market_score"]) if ms.get("available") else None
        steps["market_sentiment"] = "ok" if ms.get("available") else f"unavailable: {ms.get('reason','')}"
    except Exception as e:
        factor_scores["market_sentiment"] = None
        steps["market_sentiment"] = f"FAIL: {e}"

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
