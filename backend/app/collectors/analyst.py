"""애널리스트 컨센서스 수집 — yfinance 사용.

수집 항목:
  - 평균 목표주가 & 상승여력
  - 투자의견 분포 (strongBuy / buy / hold / sell / strongSell)
  - 최근 등급 변경 (upgrade/downgrade 건수)

KOSDAQ: 데이터 미제공 → available=False
캐시 TTL: 24시간 (장중에 거의 변하지 않음)
"""
from __future__ import annotations

import math
import logging
from datetime import datetime, timedelta, timezone

from app.collectors import cache

logger = logging.getLogger(__name__)
_TTL = 86400  # 24시간


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def get_analyst_data(ticker: str, market: str) -> dict:
    """
    Returns:
        {
          mean_target: float | None,     # 평균 목표주가
          current_price: float | None,   # 현재가
          upside_pct: float | None,      # 상승여력 %
          strong_buy: int,
          buy: int,
          hold: int,
          sell: int,
          strong_sell: int,
          num_analysts: int,
          upgrades_3m: int,              # 최근 90일 등급 상향 수
          downgrades_3m: int,            # 최근 90일 등급 하향 수
          available: bool,
        }
    """
    key = f"analyst:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    if market.upper() != "NASDAQ":
        result = {"available": False, "reason": "KOSDAQ analyst data not available via yfinance"}
        return result

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)

        # 목표주가
        targets = t.analyst_price_targets or {}
        mean_target = _nav(targets.get("mean"))

        # 현재가
        try:
            current_price = _nav(t.fast_info.last_price)
        except Exception:
            current_price = None

        upside_pct: float | None = None
        if mean_target and current_price and current_price > 0:
            upside_pct = round((mean_target - current_price) / current_price * 100, 2)

        # 투자의견 분포 (가장 최근 컨센서스)
        strong_buy = buy = hold = sell = strong_sell = 0
        try:
            recs = t.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[-1]
                strong_buy  = int(latest.get("strongBuy",  0) or 0)
                buy         = int(latest.get("buy",         0) or 0)
                hold        = int(latest.get("hold",        0) or 0)
                sell        = int(latest.get("sell",        0) or 0)
                strong_sell = int(latest.get("strongSell",  0) or 0)
        except Exception:
            pass

        num_analysts = strong_buy + buy + hold + sell + strong_sell

        # 최근 90일 등급 변경
        upgrades_3m = downgrades_3m = 0
        try:
            ud = t.upgrades_downgrades
            if ud is not None and not ud.empty:
                cutoff = datetime.now(timezone.utc) - timedelta(days=90)
                # 인덱스가 DatetimeIndex인 경우
                if hasattr(ud.index, "tz_localize"):
                    try:
                        ud.index = ud.index.tz_localize("UTC") if ud.index.tzinfo is None else ud.index.tz_convert("UTC")
                    except Exception:
                        pass
                recent = ud[ud.index >= cutoff] if not ud.empty else ud
                if "Action" in recent.columns:
                    actions = recent["Action"].str.lower()
                    upgrades_3m   = int((actions == "up").sum())
                    downgrades_3m = int((actions == "down").sum())
        except Exception:
            pass

        result = {
            "mean_target":    mean_target,
            "current_price":  current_price,
            "upside_pct":     upside_pct,
            "strong_buy":     strong_buy,
            "buy":            buy,
            "hold":           hold,
            "sell":           sell,
            "strong_sell":    strong_sell,
            "num_analysts":   num_analysts,
            "upgrades_3m":    upgrades_3m,
            "downgrades_3m":  downgrades_3m,
            "available":      True,
        }
        if num_analysts > 0 or mean_target:
            cache.set(key, result, _TTL)
        return result

    except Exception as e:
        logger.warning("analyst data failed for %s: %s", ticker, e)
        return {"available": False, "reason": str(e)}
