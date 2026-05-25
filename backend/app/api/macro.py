"""GET /macro — global macro dashboard endpoint (T25)."""
from __future__ import annotations

import math

from fastapi import APIRouter

from app.collectors.macro import get_macro

router = APIRouter()


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


@router.get("/macro")
def macro_dashboard() -> dict:
    """Return a consolidated macro snapshot for the dashboard."""
    # Fetch macro data for both markets (NASDAQ gives US indicators; KR adds ECOS)
    us = get_macro("", "NASDAQ")
    kr = get_macro("", "KOSDAQ")

    indicators = {
        # US rates & yields
        "fed_rate": _clean(us.get("fed_rate")),
        "us_10y": _clean(us.get("us_10y")),
        "yield_curve": _clean(us.get("yield_curve")),
        # KR rates
        "bok_rate": _clean(kr.get("bok_rate")),
        # FX
        "usdkrw": _clean(us.get("usdkrw")),
        "dxy": _clean(us.get("dxy")),
        # Inflation
        "us_cpi": _clean(us.get("us_cpi")),
        "kr_cpi": _clean(kr.get("kr_cpi")),
        # Sentiment
        "vix": _clean(us.get("vix")),
        "us_pmi": _clean(us.get("us_pmi")),
        # Equity indices (60d return %)
        "sp500_60d": _clean(us.get("sp500_60d")),
        "nasdaq_60d": _clean(us.get("nasdaq_60d")),
        "sox_60d": _clean(us.get("sox_60d")),
        # Commodities
        "oil": _clean(us.get("oil")),
        "copper": _clean(us.get("copper")),
    }

    return {
        "as_of": us.get("as_of"),
        "regime": us.get("regime"),
        "sector_hints": us.get("sector_hints", []),
        "fred_available": us.get("fred_available", False),
        "ecos_available": us.get("ecos_available", False),
        "indicators": indicators,
    }
