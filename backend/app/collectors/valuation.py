"""Valuation data collector — PER/PBR/PSR/EV-EBITDA/배당수익률 + 5y historical position."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.collectors import cache

_TTL = 86400  # 1 day


def _safe(val: Any, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        import math
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _get_kr_valuation(ticker: str) -> dict:
    from pykrx import stock as pykrx_stock

    end = datetime.now(timezone.utc).strftime("%Y%m%d")
    start_5y = (datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year - 5)
                ).strftime("%Y%m%d")

    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "source": "pykrx", "available": True,
    }
    try:
        # Current fundamental (PER, PBR, div yield)
        df = pykrx_stock.get_market_fundamental(end, end, ticker)
        if df is not None and not df.empty:
            row = df.iloc[-1]
            result["per"] = _safe(row.get("PER") or row.get("per"))
            result["pbr"] = _safe(row.get("PBR") or row.get("pbr"))
            dps = _safe(row.get("DIV") or row.get("div"))
            result["dividend_yield"] = dps  # already in % from pykrx

        # 5-year historical PER for percentile position
        df5 = pykrx_stock.get_market_fundamental(start_5y, end, ticker)
        if df5 is not None and not df5.empty:
            per_col = "PER" if "PER" in df5.columns else "per"
            per_series = df5[per_col].replace(0, None).dropna()
            if len(per_series) > 10 and result["per"] is not None:
                pct = (per_series < result["per"]).mean() * 100
                result["per_5y_pct"] = round(pct, 1)
    except Exception:
        result["available"] = False

    # Mark unavailable if core metrics all None (e.g., KRX API down)
    if result["per"] is None and result["pbr"] is None:
        result["available"] = False
    return result


def _get_us_valuation(ticker: str) -> dict:
    import yfinance as yf

    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "source": "yfinance", "available": True,
    }
    try:
        info = yf.Ticker(ticker).info
        result["per"] = _safe(info.get("trailingPE") or info.get("forwardPE"))
        result["pbr"] = _safe(info.get("priceToBook"))
        dy = _safe(info.get("dividendYield"))
        result["dividend_yield"] = round(dy * 100, 2) if dy else None
        result["psr"] = _safe(info.get("priceToSalesTrailing12Months"))
        result["ev_ebitda"] = _safe(info.get("enterpriseToEbitda"))
    except Exception:
        result["available"] = False
    return result


def get_valuation(ticker: str, market: str) -> dict:
    key = f"valuation:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    data = _get_kr_valuation(ticker) if market == "KOSDAQ" else _get_us_valuation(ticker)
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    cache.set(key, data, _TTL)
    return data
