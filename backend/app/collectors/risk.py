"""Risk data collector — volatility/beta from price + KR disclosures via DART."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.collectors import cache

_TTL = 86400


def _safe(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        import math
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _compute_atr_pct(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 1:
        return None
    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return _safe(atr / close.iloc[-1] * 100)
    except Exception:
        return None


def _compute_beta(price_df: pd.DataFrame, index_df: pd.DataFrame | None,
                  period: int = 60) -> float | None:
    if index_df is None or len(price_df) < period or len(index_df) < period:
        return None
    try:
        stock_ret = price_df["close"].astype(float).pct_change().dropna().iloc[-period:]
        idx_ret = index_df["close"].astype(float).pct_change().dropna().iloc[-period:]
        min_len = min(len(stock_ret), len(idx_ret))
        if min_len < 20:
            return None
        s, i = stock_ret.iloc[-min_len:].values, idx_ret.iloc[-min_len:].values
        cov = np.cov(s, i)[0][1]
        var = np.var(i)
        return _safe(cov / var) if var > 0 else None
    except Exception:
        return None


def get_risk_price(price_df: pd.DataFrame, index_df: pd.DataFrame | None = None) -> dict:
    """Price-derived risk inputs (no API key needed)."""
    return {
        "atr_pct": _compute_atr_pct(price_df),
        "beta": _compute_beta(price_df, index_df),
        "dart_available": False,
        "source": "price",
    }


def get_risk_dart(ticker: str) -> dict:
    """KR disclosure risk inputs via DART."""
    dart_key = os.environ.get("DART_API_KEY")
    result: dict = {
        "high_debt": False, "low_interest_coverage": False,
        "audit_opinion_bad": False, "cb_bw_outstanding": False,
        "dart_available": bool(dart_key),
        "key_required": None if dart_key else "DART_API_KEY",
    }
    if not dart_key:
        return result
    try:
        import OpenDartReader as dart
        dr = dart.OpenDartReader(dart_key)
        corp = dr.find_corp_code(ticker)
        if corp is None or corp.empty:
            return result
        corp_code = corp.iloc[0]["corp_code"]

        year = datetime.now(timezone.utc).year
        # Audit opinion
        for y in [year - 1, year - 2]:
            try:
                audit = dr.audie(corp_code, y)
                if audit is not None and not audit.empty:
                    opinion = str(audit.iloc[0].get("opinion", ""))
                    if any(w in opinion for w in ["한정", "부적정", "의견거절"]):
                        result["audit_opinion_bad"] = True
                    break
            except Exception:
                pass

        # CB/BW (전환사채/신주인수권부사채) — search disclosures
        try:
            disc = dr.list(corp_code, kind="B", start="20230101")
            if disc is not None and not disc.empty:
                titles = " ".join(disc["report_nm"].tolist())
                if any(w in titles for w in ["전환사채", "신주인수권"]):
                    result["cb_bw_outstanding"] = True
        except Exception:
            pass

    except Exception as e:
        result["dart_available"] = False
        result["error"] = str(e)
    return result


def get_risk(ticker: str, market: str,
             price_df: pd.DataFrame = None, index_df: pd.DataFrame = None) -> dict:
    key = f"risk:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    price_risk = get_risk_price(price_df, index_df) if price_df is not None else {}
    dart_risk = get_risk_dart(ticker) if market in ("KOSDAQ", "KOSPI") else {}

    data = {**price_risk, **dart_risk, "as_of": datetime.now(timezone.utc).isoformat()}
    cache.set(key, data, _TTL)
    return data
