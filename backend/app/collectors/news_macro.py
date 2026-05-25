"""거시 환경 뉴스 수집 — NewsAPI.org 사용.

무료 플랜: 100 req/day, 지난 1개월 기사
NEWSAPI_KEY 환경변수 필요.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_BASE = "https://newsapi.org/v2/everything"

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
