"""GET /screen — batch screener endpoint."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.collectors.universe import get_universe
from app.services.screener import run_screen

router = APIRouter()

_last_result: dict | None = None
_running = False
_last_run_at: str | None = None
_lock = threading.Lock()


def _run_in_background(tickers: list[dict], market_filter: str | None) -> None:
    global _running, _last_result, _last_run_at
    try:
        results = run_screen(tickers, min_composite=0.0, market_filter=market_filter)
        with _lock:
            _last_result = {"results": results, "market": market_filter}
            _last_run_at = datetime.now(timezone.utc).isoformat()
    except Exception:
        pass
    finally:
        with _lock:
            _running = False


@router.get("/screen")
def screen(
    market: str = Query("", description="Filter: KOSDAQ | NASDAQ | (empty = both)"),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    global _running

    market_filter = market.upper() if market else None

    with _lock:
        already_running = _running
        has_cache = _last_result is not None

    # 캐시 있으면 바로 반환
    if has_cache:
        return _build_response(_last_result, min_score, limit, stale=already_running)

    # 캐시 없고 실행 중이면 대기 중 응답
    if already_running:
        return {"status": "running", "results": [], "total": 0, "stale": True}

    # 처음 요청 → 백그라운드에서 실행 시작
    tickers = get_universe(market_filter)
    with _lock:
        _running = True

    thread = threading.Thread(
        target=_run_in_background,
        args=(tickers, market_filter),
        daemon=True,
    )
    thread.start()

    return {"status": "running", "results": [], "total": 0, "stale": True}


def _build_response(cache: dict, min_score: float, limit: int, stale: bool) -> dict:
    results = cache.get("results", [])
    filtered = [r for r in results if (r.get("composite") or 0) >= min_score]
    return {
        "status": "ok",
        "stale": stale,
        "total": len(filtered),
        "results": filtered[:limit],
        "as_of": _last_run_at,
    }
