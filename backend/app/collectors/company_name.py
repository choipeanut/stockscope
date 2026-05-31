"""Company name lookup — KOSDAQ (static map) + NASDAQ (yfinance, cached).

캐시: 24시간 in-memory. 서버 재시작 시 초기화.
"""
from __future__ import annotations

import time

# ── KOSDAQ / KOSPI static name map (universe.py 기반) ────────────────────────

_KOSDAQ_NAMES: dict[str, str] = {
    # KOSPI 대형주
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "035420": "NAVER",
    "005490": "POSCO홀딩스",
    "000270": "기아",
    "105560": "KB금융",
    "055550": "신한지주",
    "028260": "삼성물산",
    "012330": "현대모비스",
    "066570": "LG전자",
    "003550": "LG",
    "034730": "SK",
    "017670": "SK텔레콤",
    # KOSDAQ 대형주
    "068270": "셀트리온",
    "035720": "카카오",
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "196170": "알테오젠",
    "263750": "펄어비스",
    "041510": "에스엠",
    "036570": "엔씨소프트",
    "112040": "위메이드",
    "091990": "셀트리온헬스케어",
    "122870": "와이지엔터테인먼트",
    "095340": "ISC",
    "039030": "이오테크닉스",
    "214150": "클래시스",
    "145020": "휴젤",
    # 자주 조회되는 추가 종목
    "373220": "LG에너지솔루션",
    "000100": "유한양행",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "035900": "JYP엔터",
    "018260": "삼성에스디에스",
    "010130": "고려아연",
    "326030": "SK바이오팜",
    "009150": "삼성전기",
    "011200": "HMM",
}

# ── NASDAQ / US in-memory cache ───────────────────────────────────────────────

_nasdaq_cache: dict[str, tuple[str, float]] = {}  # ticker → (name, expire_ts)
_NASDAQ_TTL = 86_400.0  # 24 hours


def _fetch_nasdaq_name(ticker: str) -> str:
    """yfinance로 NASDAQ 종목명 조회. 실패 시 빈 문자열 반환."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        name = info.get("shortName") or info.get("longName") or ""
        return str(name)
    except Exception:
        return ""


def _fetch_kr_name(ticker: str) -> str:
    """pykrx로 한국 종목명 조회. 실패 시 빈 문자열."""
    try:
        from pykrx import stock
        name = stock.get_market_ticker_name(ticker)
        return str(name) if name else ""
    except Exception:
        return ""


def get_company_name(ticker: str, market: str) -> str:
    """종목 코드 → 회사명 반환. 조회 실패 시 빈 문자열."""
    if market == "KOSDAQ":
        # 1) 정적 맵 우선 (빠름)
        t = ticker.upper()
        name = _KOSDAQ_NAMES.get(t, "")
        if name:
            return name
        # 2) pykrx fallback (정적 맵에 없는 모든 한국 종목)
        cached = _nasdaq_cache.get(t)
        if cached and time.time() < cached[1]:
            return cached[0]
        name = _fetch_kr_name(t)
        _nasdaq_cache[t] = (name, time.time() + _NASDAQ_TTL)
        return name

    # NASDAQ (or unknown)
    t = ticker.upper()
    cached = _nasdaq_cache.get(t)
    if cached and time.time() < cached[1]:
        return cached[0]

    name = _fetch_nasdaq_name(t)
    _nasdaq_cache[t] = (name, time.time() + _NASDAQ_TTL)
    return name
