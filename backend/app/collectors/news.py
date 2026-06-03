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
            try:
                content = n.get("content") or {}
                # yfinance v0.2.x returns nested content dict
                title = content.get("title") or n.get("title", "")
                url = (
                    (content.get("canonicalUrl") or {}).get("url")
                    or (content.get("clickThroughUrl") or {}).get("url")
                    or n.get("link", "")
                )
                pub_ts = content.get("pubDate") or n.get("providerPublishTime")
                if isinstance(pub_ts, (int, float)):
                    published = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
                elif isinstance(pub_ts, str):
                    published = pub_ts
                else:
                    published = ""

                provider = (
                    (content.get("provider") or {}).get("displayName") or n.get("publisher", "")
                )
                summary = content.get("summary", "")

                if title:
                    items.append({
                        "title": title,
                        "url": url or "",
                        "source": provider,
                        "published": published,
                        "summary": summary[:200] if summary else "",
                        "type": "news",
                    })
            except Exception:
                continue
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


def _fetch_dart_disclosures(ticker: str, limit: int = 10,
                            start_date: str | None = None,
                            end_date: str | None = None) -> list[dict]:
    """Recent DART disclosures for a ticker.

    `start_date`/`end_date` are ISO date/datetime strings; when given they
    override the default trailing-90-day window (used by the reflection loop to
    fetch only what was disclosed during a pick's holding period).
    """
    dart_key = os.environ.get("DART_API_KEY")
    if not dart_key:
        return []
    try:
        from app.collectors.dart_fundamentals import make_reader, quiet_stdout
        dart = make_reader(dart_key)
        corp_code = _corp_code(dart, ticker)
        if not corp_code:
            return []

        def _yyyymmdd(s: str) -> str:
            return str(s)[:10].replace("-", "")[:8]

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        bgn_de = _yyyymmdd(start_date) if start_date else start.strftime("%Y%m%d")
        end_de = _yyyymmdd(end_date) if end_date else end.strftime("%Y%m%d")
        with quiet_stdout():
            df = dart.list(corp_code, bgn_de=bgn_de, end_de=end_de)
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
    macro_news: list[dict] = []

    if market.upper() == "NASDAQ":
        news = _fetch_yf_news(ticker, limit)
    else:
        # KOSDAQ: DART 공시 우선, 뉴스는 yfinance로 시도
        disclosures = _fetch_dart_disclosures(ticker, limit)
        news = _fetch_yf_news(ticker, min(5, limit))

    # 거시 환경 뉴스 (NewsAPI) — 화면 표시용만, 감성 분석에는 넣지 않음
    # (시장 전반 영향은 market_sentiment 팩터에서 별도 처리)
    from app.collectors.news_macro import get_macro_news
    macro_news = get_macro_news(ticker, market, limit=5)

    # 감성 분석 (Claude) — 종목 직접 뉴스 + 공시만 분석
    from app.services.sentiment import analyze_sentiment
    sentiment = analyze_sentiment(ticker, market, news, disclosures)

    result = {
        "ticker": ticker,
        "market": market,
        "news": news,
        "disclosures": disclosures,
        "macro_news": macro_news,
        "sentiment": sentiment,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    # 뉴스가 있을 때만 캐시 — 빈 결과는 캐시하지 않음
    if news or disclosures or macro_news:
        cache.set(key, result, _TTL)
    return result
