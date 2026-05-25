"""Macro data collector — rates/FX/CPI/PMI/commodities/indices."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.collectors import cache

_TTL = 86400


def _safe(val: Any) -> float | None:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _fred_latest(fred, series_id: str) -> float | None:
    try:
        s = fred.get_series(series_id, observation_start="2020-01-01")
        if s is None or s.empty:
            return None
        return _safe(s.dropna().iloc[-1])
    except Exception:
        return None


def _ecos_latest(api_key: str, stat_code: str, item_code: str = "?") -> float | None:
    """Simple ECOS API call — returns latest value."""
    import requests
    end = datetime.now(timezone.utc).strftime("%Y%m")
    start = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y%m")
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1"
        f"/{stat_code}/MM/{start}/{end}/{item_code}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        rows = data.get("StatisticSearch", {}).get("row", [])
        if not rows:
            return None
        return _safe(rows[-1].get("DATA_VALUE"))
    except Exception:
        return None


def _yf_latest(symbol: str, period: str = "5d") -> float | None:
    import yfinance as yf
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            return None
        return _safe(float(hist["Close"].iloc[-1]))
    except Exception:
        return None


def _yf_return(symbol: str, days: int = 60) -> float | None:
    import yfinance as yf
    try:
        hist = yf.Ticker(symbol).history(period=f"{days + 10}d")
        if hist.empty or len(hist) < 2:
            return None
        r = (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]
        return _safe(float(r) * 100)
    except Exception:
        return None


def get_macro(ticker: str = "", market: str = "NASDAQ") -> dict:
    key = f"macro:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    fred_key = os.environ.get("FRED_API_KEY")
    ecos_key = os.environ.get("ECOS_API_KEY")

    result: dict = {
        # US rates
        "fed_rate": None, "us_10y": None, "yield_curve": None,
        # KR rates
        "bok_rate": None, "kr_10y": None,
        # FX
        "usdkrw": None, "dxy": None,
        # Inflation
        "us_cpi": None, "kr_cpi": None,
        # Growth / sentiment
        "us_pmi": None, "vix": None,
        # Indices
        "sp500_60d": None, "nasdaq_60d": None, "sox_60d": None,
        # Commodities
        "oil": None, "copper": None,
        # Key required flags
        "fred_available": bool(fred_key),
        "ecos_available": bool(ecos_key),
        "key_required": [],
        "source": "FRED+ECOS+yfinance",
        "available": True,
    }

    if not fred_key:
        result["key_required"].append("FRED_API_KEY")
    if not ecos_key:
        result["key_required"].append("ECOS_API_KEY")

    # yfinance-sourced (no keys)
    result["vix"] = _yf_latest("^VIX")
    result["dxy"] = _yf_latest("DX-Y.NYB")
    result["usdkrw"] = _yf_latest("USDKRW=X")
    result["sp500_60d"] = _yf_return("^GSPC", 60)
    result["nasdaq_60d"] = _yf_return("^IXIC", 60)
    result["sox_60d"] = _yf_return("^SOX", 60)
    result["oil"] = _yf_latest("CL=F")
    result["copper"] = _yf_latest("HG=F")
    result["us_10y"] = _yf_latest("^TNX")

    # FRED (US rates, CPI, PMI)
    if fred_key:
        try:
            from fredapi import Fred
            fred = Fred(api_key=fred_key)
            result["fed_rate"] = _fred_latest(fred, "FEDFUNDS")
            result["us_cpi"] = _fred_latest(fred, "CPIAUCSL")
            result["us_pmi"] = _fred_latest(fred, "NAPM")
            us_2y = _fred_latest(fred, "DGS2")
            us_10y_fred = _fred_latest(fred, "DGS10")
            if us_2y and us_10y_fred:
                result["yield_curve"] = us_10y_fred - us_2y
            if us_10y_fred:
                result["us_10y"] = us_10y_fred
        except Exception:
            pass

    # ECOS (KR rates, CPI)
    if ecos_key:
        # 722Y001: 기준금리, 817Y002: CPI
        result["bok_rate"] = _ecos_latest(ecos_key, "722Y001", "0101000")
        result["kr_cpi"] = _ecos_latest(ecos_key, "901Y009", "0")

    result["as_of"] = datetime.now(timezone.utc).isoformat()

    # Regime determination
    result["regime"] = _determine_regime(result)
    result["sector_hints"] = _sector_hints(result["regime"], market)

    cache.set(key, result, _TTL)
    return result


def _determine_regime(m: dict) -> str:
    """경기 국면: 회복 / 확장 / 둔화 / 침체."""
    bullish = 0
    bearish = 0

    if m.get("nasdaq_60d") is not None:
        if m["nasdaq_60d"] > 5:
            bullish += 1
        elif m["nasdaq_60d"] < -5:
            bearish += 1

    if m.get("yield_curve") is not None:
        if m["yield_curve"] > 0:
            bullish += 1
        else:
            bearish += 1

    if m.get("vix") is not None:
        if m["vix"] < 20:
            bullish += 1
        elif m["vix"] > 30:
            bearish += 2

    if m.get("us_pmi") is not None:
        if m["us_pmi"] > 52:
            bullish += 1
        elif m["us_pmi"] < 48:
            bearish += 1

    if bullish > bearish + 1:
        return "확장"
    elif bullish > bearish:
        return "회복"
    elif bearish > bullish + 1:
        return "침체"
    else:
        return "둔화"


def _sector_hints(regime: str, market: str) -> list[str]:
    hints = {
        "확장": ["기술주/성장주 유리", "경기민감주 유리", "방어주 주의"],
        "회복": ["경기민감주 유리", "금융주 유리", "필수소비재 중립"],
        "둔화": ["방어주(헬스케어/통신/필수소비) 유리", "성장주 주의", "배당주 선호"],
        "침체": ["방어주 최우선", "현금·채권 선호", "성장주·경기민감주 회피"],
    }
    return hints.get(regime, [])
