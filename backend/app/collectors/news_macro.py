"""거시 환경 뉴스 수집 — NewsAPI.org 사용.

무료 플랜: 100 req/day, 지난 1개월 기사
NEWSAPI_KEY 환경변수 필요.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BASE = "https://newsapi.org/v2/everything"

# NewsAPI 무료 플랜은 하루 100회. analyze마다 호출하면 금방 소진되므로
# 시장 전반(ticker 무관) 뉴스는 프로세스 전역 캐시로 재사용한다.
_global_cache: dict = {}              # {"data": [...], "ts": epoch}
_GLOBAL_TTL_OK = 3600                 # 성공 결과 1시간
_GLOBAL_TTL_EMPTY = 900              # 빈 결과(할당량/오류)도 15분 캐시 → 재호출 폭주 방지

# 마지막으로 관측된 NewsAPI 오류(예: 429 rateLimited) — unavailable 사유 표면화용
_last_error: dict = {}               # {"code": int, "message": str}

# 종목별 섹터 키워드 매핑 (없으면 general macro)
_SECTOR_KEYWORDS: dict[str, str] = {
    "AAPL": "Apple semiconductor technology",
    "MSFT": "Microsoft cloud AI technology",
    "GOOGL": "Google Alphabet advertising AI",
    "AMZN": "Amazon ecommerce cloud",
    "NVDA": "Nvidia semiconductor AI GPU",
    "TSLA": "Tesla EV electric vehicle",
    "META": "Meta Facebook social media",
}

_MACRO_QUERY = (
    "Federal Reserve interest rate OR"
    " US China trade war tariff OR"
    " inflation recession economy OR"
    " geopolitical risk war sanctions OR"
    " stock market S&P NASDAQ"
)

# 글로벌 시장 전반 분석용 쿼리 (ticker 무관). NewsAPI 일일 할당량을 아끼려고
# 폭넓은 2개로 압축 — 감성 판단에는 충분하다.
_GLOBAL_QUERIES = [
    "Federal Reserve interest rate inflation recession economy monetary policy",
    "stock market S&P 500 NASDAQ VIX volatility China trade war geopolitical",
]


def _fetch(query: str, api_key: str, limit: int = 5) -> list[dict]:
    """NewsAPI /everything 호출."""
    import requests

    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = requests.get(
            _BASE,
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": limit,
                "from": since,
                "apiKey": api_key,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            # 사유 표면화 (특히 429 rateLimited = 일일 할당량 소진)
            try:
                body = resp.json()
                _last_error.update({"code": resp.status_code,
                                    "message": body.get("message", "")})
            except Exception:
                _last_error.update({"code": resp.status_code, "message": ""})
            logger.warning("NewsAPI %s: %s", resp.status_code,
                           _last_error.get("message", ""))
            return []
        articles = resp.json().get("articles", [])
        items = []
        for a in articles:
            title = a.get("title", "") or ""
            url = a.get("url", "") or ""
            if not title or title == "[Removed]":
                continue
            items.append({
                "title": title,
                "url": url,
                "source": (a.get("source") or {}).get("name", ""),
                "published": a.get("publishedAt", ""),
                "summary": (a.get("description") or "")[:200],
                "type": "macro_news",
            })
        return items
    except Exception:
        return []


def get_macro_news(ticker: str, market: str, limit: int = 5) -> list[dict]:
    """
    거시 환경 뉴스 + 섹터 관련 뉴스 반환.
    NEWSAPI_KEY 없으면 빈 리스트.
    """
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []

    results: list[dict] = []

    # 1) 종목 직접 검색 (ticker 심볼 + 회사명 힌트)
    ticker_query = _SECTOR_KEYWORDS.get(ticker.upper(), ticker)
    results.extend(_fetch(ticker_query, api_key, limit=3))

    # 2) 거시 환경 뉴스
    results.extend(_fetch(_MACRO_QUERY, api_key, limit=limit))

    # 중복 제거 (url 기준)
    seen: set[str] = set()
    unique = []
    for item in results:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    return unique[:limit * 2]


def get_global_market_news(limit_per_category: int = 4) -> list[dict]:
    """
    글로벌 시장 전반 뉴스 수집 (ticker 무관).
    5개 카테고리에서 수집 후 중복 제거하여 반환.
    NEWSAPI_KEY 없으면 빈 리스트.
    """
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []

    # 캐시 확인 (시장 공통 — 종목 무관). 성공/빈 결과 모두 캐시해 호출 폭주 방지.
    entry = _global_cache.get("entry")
    if entry:
        age = time.time() - entry["ts"]
        ttl = _GLOBAL_TTL_OK if entry["data"] else _GLOBAL_TTL_EMPTY
        if age < ttl:
            return entry["data"]

    results: list[dict] = []
    for query in _GLOBAL_QUERIES:
        results.extend(_fetch(query, api_key, limit=limit_per_category))

    seen: set[str] = set()
    unique = []
    for item in results:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    _global_cache["entry"] = {"data": unique, "ts": time.time()}
    return unique


def last_newsapi_error() -> dict:
    """가장 최근 NewsAPI 오류(있으면). unavailable 사유 표면화용."""
    return dict(_last_error)
