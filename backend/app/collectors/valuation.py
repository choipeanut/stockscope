"""Valuation data collector — PER/PBR/PSR/EV-EBITDA/배당수익률."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

from app.collectors import cache

_TTL = 3600  # 1시간 (rate limit 우회용 단축)


def _safe(val: Any, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _get_kr_valuation(ticker: str) -> dict:
    from pykrx import stock as pykrx_stock

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "eps": None, "bps": None,
        "source": "pykrx", "available": True,
    }
    try:
        df = pykrx_stock.get_market_fundamental(today, today, ticker)
        if df is not None and not df.empty:
            row = df.iloc[-1]
            result["per"] = _safe(row.get("PER") or row.get("per"))
            result["pbr"] = _safe(row.get("PBR") or row.get("pbr"))
            result["eps"] = _safe(row.get("EPS") or row.get("eps"))
            result["bps"] = _safe(row.get("BPS") or row.get("bps"))
            dps = _safe(row.get("DIV") or row.get("div"))
            result["dividend_yield"] = dps
        # 5y PER percentile
        start_5y = (datetime.now(timezone.utc).replace(
            year=datetime.now(timezone.utc).year - 5)
        ).strftime("%Y%m%d")
        df5 = pykrx_stock.get_market_fundamental(start_5y, today, ticker)
        if df5 is not None and not df5.empty and result["per"] is not None:
            per_col = "PER" if "PER" in df5.columns else "per"
            per_s = df5[per_col].replace(0, None).dropna()
            if len(per_s) > 10:
                result["per_5y_pct"] = round(
                    (per_s < result["per"]).mean() * 100, 1
                )
    except Exception:
        result["available"] = False

    if result["per"] is None and result["pbr"] is None:
        result["available"] = False
    return result


def _get_us_valuation(ticker: str, retries: int = 3) -> dict:
    import yfinance as yf

    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "eps": None, "bps": None, "market_cap": None,
        "forward_pe": None, "peg_ratio": None,
        "source": "yfinance", "available": False,
    }

    tk = yf.Ticker(ticker)

    # 1) fast_info 먼저 시도 (rate limit 영향 적음)
    for attempt in range(retries):
        try:
            fi = tk.fast_info
            result["per"] = _safe(getattr(fi, "pe_ratio", None))
            result["market_cap"] = _safe(getattr(fi, "market_cap", None))
            result["available"] = True
            break
        except Exception:
            if attempt < retries - 1:
                time.sleep(3)

    # 2) info 추가 시도 (더 많은 지표)
    for attempt in range(retries):
        try:
            info = tk.info
            if info:
                result["per"] = result["per"] or _safe(
                    info.get("trailingPE") or info.get("forwardPE")
                )
                result["forward_pe"] = _safe(info.get("forwardPE"))
                result["pbr"] = _safe(info.get("priceToBook"))
                result["psr"] = _safe(info.get("priceToSalesTrailing12Months"))
                result["ev_ebitda"] = _safe(info.get("enterpriseToEbitda"))
                result["peg_ratio"] = _safe(info.get("pegRatio"))
                result["eps"] = _safe(info.get("trailingEps"))
                result["market_cap"] = result["market_cap"] or _safe(
                    info.get("marketCap")
                )
                dy = _safe(info.get("dividendYield"))
                result["dividend_yield"] = round(dy * 100, 2) if dy else None
                result["available"] = True
                break
        except Exception:
            if attempt < retries - 1:
                time.sleep(3)

    return result


def get_valuation(ticker: str, market: str) -> dict:
    key = f"valuation:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    data = _get_kr_valuation(ticker) if market == "KOSDAQ" else _get_us_valuation(ticker)
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    if data.get("available"):
        cache.set(key, data, _TTL)
    return data
