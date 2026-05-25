"""GET /screen — batch screener endpoint (T22)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.collectors.universe import get_universe
from app.services.screener import run_screen

router = APIRouter()

# Simple in-memory cache for the last screen run
_last_result: dict | None = None
_running = False


@router.get("/screen")
def screen(
    market: str = Query("", description="Filter: KOSDAQ | NASDAQ | (empty = both)"),
    min_score: float = Query(0.0, ge=0.0, le=100.0, description="Min composite score"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    background_tasks: BackgroundTasks = None,
) -> dict:
    """
    Run a batch composite-score screen across the configured universe.
    The first call may take 30-120 seconds; subsequent calls hit cache.
    Add ?fresh=true to force a re-run.
    """
    global _running, _last_result

    if market and market.upper() not in ("KOSDAQ", "NASDAQ"):
        raise HTTPException(status_code=400, detail="market must be KOSDAQ or NASDAQ")

    market_filter = market.upper() if market else None
    tickers = get_universe(market_filter)

    if _running:
        # A run is already in progress — return the stale result if any
        if _last_result:
            return _build_response(_last_result, min_score, limit, stale=True)
        return {"status": "running", "results": [], "total": 0, "stale": True}

    _running = True
    try:
        results = run_screen(tickers, min_composite=min_score, market_filter=market_filter)
        _last_result = {"results": results, "market": market_filter}
    finally:
        _running = False

    return _build_response(_last_result, min_score, limit, stale=False)


def _build_response(cache: dict, min_score: float, limit: int, stale: bool) -> dict:
    results = cache.get("results", [])
    filtered = [r for r in results if (r.get("composite") or 0) >= min_score]
    return {
        "status": "ok",
        "stale": stale,
        "total": len(filtered),
        "results": filtered[:limit],
    }
