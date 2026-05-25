"""GET /news — 뉴스 & 공시 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.collectors.news import get_news

router = APIRouter()


@router.get("/news")
def news(
    ticker: str = Query(...),
    market: str = Query(...),
    limit: int = Query(10, ge=1, le=30),
) -> dict:
    return get_news(ticker.upper(), market.upper(), limit)
