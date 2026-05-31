"""내부자 거래 수집 — yfinance 사용.

수집 항목:
  - 최근 90일 임원/대주주 순매수 금액
  - 매수 건수 / 매도 건수

KOSDAQ: 데이터 미제공 → available=False
캐시 TTL: 24시간
"""
from __future__ import annotations

import logging

from app.collectors import cache

logger = logging.getLogger(__name__)
_TTL = 86400  # 24시간


def get_insider_data(ticker: str, market: str) -> dict:
    """
    Returns:
        {
          buy_count:  int,    # 매수 건수
          sell_count: int,    # 매도 건수
          buy_value:  float,  # 매수 총금액 ($)
          sell_value: float,  # 매도 총금액 ($)
          net_value:  float,  # 순매수 금액 (buy - sell)
          available:  bool,
        }
    """
    key = f"insider:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    if market.upper() != "NASDAQ":
        return {"available": False, "reason": "KOSDAQ insider data not available"}

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        tx = t.insider_transactions

        if tx is None or tx.empty:
            return {"available": False, "reason": "no insider transactions found"}

        buy_count = sell_count = 0
        buy_value = sell_value = 0.0

        # 컬럼 이름은 yfinance 버전마다 다를 수 있음
        tx_col = next(
            (c for c in tx.columns if "transaction" in c.lower() or "type" in c.lower()),
            None,
        )
        val_col = next(
            (c for c in tx.columns if "value" in c.lower()),
            None,
        )

        for _, row in tx.iterrows():
            tx_type = str(row.get(tx_col, "") if tx_col else "").lower()
            raw_val = row.get(val_col, 0) if val_col else 0
            try:
                val = abs(float(raw_val or 0))
            except (TypeError, ValueError):
                val = 0.0

            if any(k in tx_type for k in ("purchase", "buy", "acquisition")):
                buy_count += 1
                buy_value += val
            elif any(k in tx_type for k in ("sale", "sell", "disposition")):
                sell_count += 1
                sell_value += val

        result = {
            "buy_count":  buy_count,
            "sell_count": sell_count,
            "buy_value":  round(buy_value, 2),
            "sell_value": round(sell_value, 2),
            "net_value":  round(buy_value - sell_value, 2),
            "available":  True,
        }
        if buy_count + sell_count > 0:
            cache.set(key, result, _TTL)
        return result

    except Exception as e:
        logger.warning("insider data failed for %s: %s", ticker, e)
        return {"available": False, "reason": str(e)}
