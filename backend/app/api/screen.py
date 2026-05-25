"""GET /screen — batch screener endpoint."""
from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.collectors.universe import get_universe
from app.services.screener import run_screen

router = APIRouter()
logger = logging.getLogger(__name__)

_last_result: dict | None = None
_running = False
_last_run_at: str | None = None
_last_error: str | None = None
_lock = threading.Lock()


def _run_in_background(tickers: list[dict], market_filter: str | None) -> None:
    global _running, _last_result, _last_run_at, _last_error
    logger.info(
        "[screener] background started: %d tickers, market=%s",
        len(tickers), market_filter
    )
    try:
        results = run_screen(tickers, min_composite=0.0, market_filter=market_filter)
        logger.info("[screener] background completed: %d results", len(results))
        with _lock:
            _last_result = {"results": results, "market": market_filter}
            _last_run_at = datetime.now(timezone.utc).isoformat()
            _last_error = None
    except Exception as e:
        err = traceback.format_exc()
        logger.error("[screener] background failed: %s\n%s", e, err)
        with _lock:
            _last_error = str(e)
    finally:
        with _lock:
            _running = False
        logger.info("[screener] background thread exiting, _running=False")


@router.get("/screen")
def screen(
    market: str = Query("", description="Filter: KOSDAQ | NASDAQ | (empty = both)"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=200),
    refresh: bool = Query(False, description="강제 새로고침"),
) -> dict:
    global _running

    market_filter = market.upper() if market else None

    with _lock:
        already_running = _running
        has_cache = _last_result is not None
        error = _last_error

    # 강제 새로고침: 캐시 클리어
    if refresh:
        with _lock:
            _last_result = None  # type: ignore[assignment]
        has_cache = False

    # 캐시 있으면 바로 반환
    if has_cache and not refresh:
        return _build_response(_last_result, min_score, limit, stale=already_running)

    # 실행 중이면 대기 중 응답
    if already_running:
        return {
            "status": "running",
            "results": [],
            "total": 0,
            "stale": True,
            "error": None,
        }

    # 이전에 오류가 있었으면 알려주기 (but still retry)
    # 처음 요청 또는 refresh → 백그라운드 실행 시작
    tickers = get_universe(market_filter)
    logger.info("[screener] starting run for %d tickers (market=%s)", len(tickers), market_filter)

    with _lock:
        _running = True

    thread = threading.Thread(
        target=_run_in_background,
        args=(tickers, market_filter),
        daemon=True,
    )
    thread.start()

    return {
        "status": "running",
        "results": [],
        "total": 0,
        "stale": True,
        "error": error,  # 이전 실행 오류가 있었으면 표시
    }


@router.get("/screen/status")
def screen_status() -> dict:
    """스크리너 백그라운드 스레드 상태 확인용 디버그 엔드포인트."""
    with _lock:
        return {
            "running": _running,
            "has_result": _last_result is not None,
            "result_count": len(_last_result.get("results", [])) if _last_result else 0,
            "last_run_at": _last_run_at,
            "last_error": _last_error,
        }


def _build_response(cache: dict, min_score: float, limit: int, stale: bool) -> dict:
    results = cache.get("results", [])
    filtered = [r for r in results if (r.get("composite") or 0) >= min_score]
    return {
        "status": "ok",
        "stale": stale,
        "total": len(filtered),
        "results": filtered[:limit],
        "as_of": _last_run_at,
        "error": None,
    }
