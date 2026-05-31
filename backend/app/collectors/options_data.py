"""옵션 시장 데이터 수집 — yfinance 사용.

수집 항목:
  - Put/Call 거래량 비율 (PCR)
  - Put/Call 미결제약정(OI) 비율
  - 평균 내재변동성 (IV)

가까운 만기 3개 기준으로 집계.
KOSDAQ: 옵션 시장 없음 → available=False
캐시 TTL: 60분
"""
from __future__ import annotations

import logging

from app.collectors import cache

logger = logging.getLogger(__name__)
_TTL = 3600  # 1시간


def get_options_data(ticker: str, market: str, max_expirations: int = 3) -> dict:
    """
    Returns:
        {
          put_call_volume_ratio: float | None,  # Put거래량 / Call거래량
          put_call_oi_ratio:     float | None,  # Put OI / Call OI
          avg_iv:                float | None,  # 평균 내재변동성 (0~1)
          call_volume:           int,
          put_volume:            int,
          call_oi:               int,
          put_oi:                int,
          available:             bool,
        }
    """
    key = f"options:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    if market.upper() != "NASDAQ":
        return {"available": False, "reason": "Korean market options not supported"}

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)

        expirations = t.options
        if not expirations:
            return {"available": False, "reason": "no options data"}

        total_call_vol = total_put_vol = 0
        total_call_oi  = total_put_oi  = 0
        iv_values: list[float] = []

        for exp in expirations[:max_expirations]:
            try:
                chain = t.option_chain(exp)
                calls = chain.calls
                puts  = chain.puts

                total_call_vol += int(calls["volume"].fillna(0).sum())
                total_put_vol  += int(puts["volume"].fillna(0).sum())
                total_call_oi  += int(calls["openInterest"].fillna(0).sum())
                total_put_oi   += int(puts["openInterest"].fillna(0).sum())

                for col in ("impliedVolatility",):
                    if col in calls.columns:
                        iv_values.extend(calls[col].dropna().tolist())
                    if col in puts.columns:
                        iv_values.extend(puts[col].dropna().tolist())
            except Exception:
                continue

        pc_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol > 0 else None
        pc_oi  = round(total_put_oi  / total_call_oi,  4) if total_call_oi  > 0 else None
        avg_iv = round(sum(iv_values) / len(iv_values), 4) if iv_values else None

        result = {
            "put_call_volume_ratio": pc_vol,
            "put_call_oi_ratio":     pc_oi,
            "avg_iv":                avg_iv,
            "call_volume":           total_call_vol,
            "put_volume":            total_put_vol,
            "call_oi":               total_call_oi,
            "put_oi":                total_put_oi,
            "available":             True,
        }
        if total_call_vol + total_put_vol > 0:
            cache.set(key, result, _TTL)
        return result

    except Exception as e:
        logger.warning("options data failed for %s: %s", ticker, e)
        return {"available": False, "reason": str(e)}
