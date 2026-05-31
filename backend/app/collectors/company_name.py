"""Company name lookup.

한국(KOSDAQ/KOSPI): FinanceDataReader KRX 전체 목록 (24시간 캐시)
NASDAQ: yfinance shortName (24시간 캐시)
"""
from __future__ import annotations
import time

# ── 공통 in-memory 캐시 ──────────────────────────────────────────────────────
_cache: dict[str, tuple[str, float]] = {}   # key → (name, expire_ts)
_TTL = 86_400.0   # 24시간

# KRX 전체 종목 목록 캐시 (1번만 로드)
_krx_map: dict[str, str] = {}   # code → name
_krx_loaded_at: float = 0.0
_KRX_TTL = 86_400.0


def _load_krx_map() -> dict[str, str]:
    """FDR로 KRX 전체 종목명 로드 (24시간 캐시)."""
    global _krx_map, _krx_loaded_at
    if _krx_map and (time.time() - _krx_loaded_at) < _KRX_TTL:
        return _krx_map
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        if df is not None and not df.empty and "Code" in df.columns and "Name" in df.columns:
            _krx_map = dict(zip(df["Code"].astype(str), df["Name"].astype(str)))
            _krx_loaded_at = time.time()
    except Exception:
        pass
    return _krx_map


def _fetch_nasdaq_name(ticker: str) -> str:
    """yfinance로 NASDAQ 종목명 조회."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        name = info.get("shortName") or info.get("longName") or ""
        return str(name)
    except Exception:
        return ""


def get_company_name(ticker: str, market: str) -> str:
    """종목 코드 → 회사명. 실패 시 빈 문자열."""
    t = ticker.upper()
    key = f"{market}:{t}"

    # 캐시 확인
    cached = _cache.get(key)
    if cached and time.time() < cached[1]:
        return cached[0]

    if market == "KOSDAQ":
        # FDR KRX 목록에서 조회
        krx = _load_krx_map()
        name = krx.get(t, "")
        if not name:
            # pykrx fallback
            try:
                from pykrx import stock
                name = str(stock.get_market_ticker_name(t) or "")
            except Exception:
                name = ""
    else:
        # NASDAQ
        name = _fetch_nasdaq_name(t)

    _cache[key] = (name, time.time() + _TTL)
    return name
