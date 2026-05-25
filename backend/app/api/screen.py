"""GET /screen — batch screener endpoint.

Design: synchronous with hard wall-clock timeout via concurrent.futures.wait().
socket.setdefaulttimeout() prevents yfinance from hanging forever.
Results cached in-process for 30 minutes.
"""
from __future__ import annotations

import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait as cf_wait
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.collectors.universe import get_universe
from app.services.screener import _safe_score_ticker  # reuse per-ticker logic

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL = 1800  # 30분
_WALL_TIMEOUT = 50  # 초 — HTTP 응답 전 최대 대기 (Render 60s 이내)
_SOCKET_TIMEOUT = 12  # 초 — 각 네트워크 소켓 타임아웃

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
    """소켓 타임아웃 + wall-clock 제한 안에서 종목 스코어링."""
    # 이 스레드 내부에서 소켓 타임아웃 설정
    orig_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(_SOCKET_TIMEOUT)

    tickers = get_universe(market_filter)
    logger.info("[screener] universe: %d tickers", len(tickers))

    results: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
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
        socket.setdefaulttimeout(orig_timeout)

    results.sort(key=lambda r: r.get("composite") or 0, reverse=True)
    return results


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
