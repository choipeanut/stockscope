"""Supply/Demand (수급) data collector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.collectors import cache

_TTL = 3600  # 1 hour


def _get_kr_flows(ticker: str) -> dict:
    from pykrx import stock as pykrx_stock

    end = datetime.now(timezone.utc).strftime("%Y%m%d")
    start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y%m%d")

    result: dict = {
        "foreign_net_5d": None, "foreign_net_20d": None,
        "institution_net_5d": None, "institution_net_20d": None,
        "individual_net_5d": None,
        "volume_ratio": None,  # avg 5d vol / avg 20d vol
        "short_ratio": None,
        "proxy": False,
        "source": "pykrx", "available": True,
    }
    try:
        df = pykrx_stock.get_market_trading_volume_by_date(start, end, ticker)
        if df is None or df.empty:
            result["available"] = False
            return result

        # Column detection
        cols = list(df.columns)
        foreign_col = next((c for c in cols if "외국" in str(c)), None)
        inst_col = next((c for c in cols if "기관" in str(c)), None)
        indiv_col = next((c for c in cols if "개인" in str(c)), None)

        if foreign_col:
            result["foreign_net_5d"] = float(df[foreign_col].iloc[-5:].sum())
            result["foreign_net_20d"] = float(df[foreign_col].sum())
        if inst_col:
            result["institution_net_5d"] = float(df[inst_col].iloc[-5:].sum())
            result["institution_net_20d"] = float(df[inst_col].sum())
        if indiv_col:
            result["individual_net_5d"] = float(df[indiv_col].iloc[-5:].sum())

        # Short selling
        try:
            short_df = pykrx_stock.get_market_short_sell_volume_by_date(start, end, ticker)
            if short_df is not None and not short_df.empty:
                vol_col = next((c for c in short_df.columns if "공매도" in str(c)
                                or "Short" in str(c)), short_df.columns[0])
                total_vol_col = next((c for c in short_df.columns if "거래량" in str(c)), None)
                if total_vol_col:
                    ratio = short_df[vol_col].sum() / short_df[total_vol_col].sum()
                    result["short_ratio"] = float(ratio) * 100
        except Exception:
            pass

        # Volume ratio (5d avg / 20d avg)
        ohlcv = pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)
        if ohlcv is not None and not ohlcv.empty:
            vcol = next((c for c in ohlcv.columns if "거래량" in str(c)), None)
            if vcol and len(ohlcv) >= 5:
                vol = ohlcv[vcol].astype(float)
                result["volume_ratio"] = float(vol.iloc[-5:].mean() / vol.mean()) \
                    if vol.mean() > 0 else None

    except Exception as e:
        result["available"] = False
        result["error"] = str(e)
    return result


def _get_us_flows(ticker: str) -> dict:
    import yfinance as yf

    result: dict = {
        "foreign_net_5d": None, "foreign_net_20d": None,
        "institution_net_5d": None, "institution_net_20d": None,
        "individual_net_5d": None,
        "volume_ratio": None,
        "short_ratio": None,
        "proxy": True,  # US uses volume-proxy
        "source": "yfinance", "available": True,
    }
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="60d")
        if hist.empty:
            result["available"] = False
            return result

        vol = hist["Volume"].astype(float)
        result["volume_ratio"] = float(vol.iloc[-5:].mean() / vol.mean()) \
            if vol.mean() > 0 else None

        info = tk.info
        inst_pct = info.get("institutionPercentHeld")
        result["institution_net_5d"] = float(inst_pct * 100) if inst_pct else None

        short_pct = info.get("shortPercentOfFloat")
        result["short_ratio"] = float(short_pct * 100) if short_pct else None

    except Exception as e:
        result["available"] = False
        result["error"] = str(e)
    return result


def get_flows(ticker: str, market: str) -> dict:
    key = f"flows:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    data = _get_kr_flows(ticker) if market == "KOSDAQ" else _get_us_flows(ticker)
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    cache.set(key, data, _TTL)
    return data
