"""News & disclosure collector.

- NASDAQ: yfinance built-in news (no key required)
- KOSDAQ: DART 공시 via OpenDartReader (DART_API_KEY required)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.collectors import cache

_TTL = 1800  # 30분 캐시


# ── NASDAQ: yfinance news ─────────────────────────────────────────────────────

def _fetch_yf_news(ticker: str, limit: int = 10) -> list[dict]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        raw = t.news or []
        items = []
        for n in raw[:limit]:
            content = n.get("content", {})
            # yfinance v0.2.x returns nested content dict
            title = content.get("title") or n.get("title", "")
            url = (
                content.get("canonicalUrl", {}).get("url")
                or content.get("clickThroughUrl", {}).get("url")
                or n.get("link", "")
            )
            pub_ts = content.get("pubDate") or n.get("providerPublishTime")
            if isinstance(pub_ts, (int, float)):
                published = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
            elif isinstance(pub_ts, str):
                published = pub_ts
            else:
                published = ""

            provider = content.get("provider", {}).get("displayName") or n.get("publisher", "")
            summary = content.get("summary", "")

            if title and url:
                items.append({
                    "title": title,
                    "url": url,
                    "source": provider,
                    "published": published,
                    "summary": summary[:200] if summary else "",
                    "type": "news",
                })
        return items
    except Exception:
        return []


# ── KOSDAQ: DART 공시 ─────────────────────────────────────────────────────────

def _corp_code(dart, ticker: str) -> str | None:
    """티커(종목코드) → DART corp_code 변환."""
    try:
        df = dart.company_by_stock_code(ticker)
        if df is not None and not df.empty:
            return str(df.iloc[0]["corp_code"])
    except Exception:
        pass
    # 대안: corp_code 검색
    try:
        df = dart.corp_codes
        match = df[df["stock_code"] == ticker]
        if not match.empty:
            return str(match.iloc[0]["corp_code"])
    except Exception:
        pass
    return None


def _fetch_dart_disclosures(ticker: str, limit: int = 10) -> list[dict]:
    dart_key = os.environ.get("DART_API_KEY")
    if not dart_key:
        return []
    try:
        import OpenDartReader
        dart = OpenDartReader.OpenDartReader(dart_key)
        corp_code = _corp_code(dart, ticker)
        if not corp_code:
            return []

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        df = dart.list(
            corp_code,
            bgn_de=start.strftime("%Y%m%d"),
            end_de=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        items = []
        for _, row in df.head(limit).iterrows():
            rcept_no = str(row.get("rcept_no", ""))
            url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
            items.append({
                "title": str(row.get("report_nm", "")),
                "url": url,
                "source": "DART",
                "published": str(row.get("rcept_dt", "")),
                "summary": str(row.get("flr_nm", "")),  # 제출인
                "type": "disclosure",
            })
        return items
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_news(ticker: str, market: str, limit: int = 10) -> dict:
    """
    Returns:
        {
          ticker, market,
          news: [...],         # 뉴스 (NASDAQ)
          disclosures: [...],  # 공시 (KOSDAQ)
          as_of: ISO string,
        }
    """
    key = f"news:{market}:{ticker}:{limit}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    news: list[dict] = []
    disclosures: list[dict] = []

    if market.upper() == "NASDAQ":
        news = _fetch_yf_news(ticker, limit)
    else:
        # KOSDAQ: DART 공시 우선, 뉴스는 yfinance로 시도
        disclosures = _fetch_dart_disclosures(ticker, limit)
        news = _fetch_yf_news(ticker, min(5, limit))

    result = {
        "ticker": ticker,
        "market": market,
        "news": news,
        "disclosures": disclosures,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    cache.set(key, result, _TTL)
    return result
