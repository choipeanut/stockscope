"""Paper trading service — buy/sell at latest price, P&L tracking.

모든 금액은 KRW 기준으로 저장.
NASDAQ 종목: USD 가격 × USD/KRW 환율로 변환 후 저장.
"""
from __future__ import annotations

import json
import time
import urllib.request

from app.collectors.prices import get_ohlcv
from app.db import repo

# 환율 캐시 (30분)
_fx_cache: dict = {}
_FX_TTL = 1800


class TradeError(ValueError):
    pass


def _get_usd_krw() -> float:
    """USD/KRW 환율 조회. 30분 캐시.
    Method 1: yfinance USDKRW=X history
    Method 2: fawazahmed0 무료 환율 API (GitHub CDN)
    Method 3: exchangerate-api.com 무료
    Fallback: 1400
    """
    now = time.time()
    if "rate" in _fx_cache and now - _fx_cache.get("ts", 0) < _FX_TTL:
        return _fx_cache["rate"]

    rate = None

    # Method 1: yfinance history (fast_info보다 FX에서 안정적)
    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not hist.empty:
            r = float(hist["Close"].iloc[-1])
            if 900 < r < 2500:
                rate = round(r, 1)
    except Exception:
        pass

    # Method 2: fawazahmed0 GitHub-hosted free API (rate limit 없음)
    if not rate:
        try:
            url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
            with urllib.request.urlopen(url, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                r = data.get("usd", {}).get("krw")
                if r and 900 < r < 2500:
                    rate = round(float(r), 1)
        except Exception:
            pass

    # Method 3: exchangerate-api.com 무료 티어
    if not rate:
        try:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            with urllib.request.urlopen(url, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                r = data.get("rates", {}).get("KRW")
                if r and 900 < r < 2500:
                    rate = round(float(r), 1)
        except Exception:
            pass

    if not rate:
        rate = 1400.0  # 최후 fallback

    _fx_cache["rate"] = rate
    _fx_cache["ts"] = now
    return rate


def _to_krw(price: float, market: str) -> tuple[float, float | None]:
    """가격을 KRW로 변환. (krw_price, fx_rate) 반환.
    KOSDAQ → (price, None), NASDAQ → (price * fx, fx)
    """
    if market == "NASDAQ":
        fx = _get_usd_krw()
        return price * fx, fx
    return price, None


def _latest_price(ticker: str, market: str) -> float:
    df = get_ohlcv(ticker, market, period_days=10)
    return float(df["close"].iloc[-1])


def buy(ticker: str, market: str, qty: float) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    price_native = _latest_price(ticker, market)
    price_krw, fx_rate = _to_krw(price_native, market)
    cost = price_krw * qty

    account = repo.get_account()
    if account["cash"] < cost:
        raise TradeError(
            f"잔고 부족: 필요 {cost:,.0f}원, 보유 {account['cash']:,.0f}원"
        )

    repo.update_cash(account["cash"] - cost)

    existing = repo.get_holding(ticker, market)
    if existing:
        old_qty = existing["qty"]
        old_avg = existing["avg_price"]
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + qty * price_krw) / new_qty
    else:
        new_qty = qty
        new_avg = price_krw

    repo.upsert_holding(ticker, market, new_qty, new_avg)
    repo.add_transaction(ticker, market, "BUY", qty, price_krw)

    result = {
        "ticker": ticker,
        "market": market,
        "side": "BUY",
        "qty": qty,
        "price": round(price_krw, 0),          # KRW 가격
        "price_native": round(price_native, 2), # 원본 가격 (USD or KRW)
        "cost": round(cost, 0),
        "avg_price": round(new_avg, 0),
        "new_qty": new_qty,
        "cash_remaining": round(account["cash"] - cost, 0),
    }
    if fx_rate:
        result["fx_rate"] = fx_rate
        result["currency"] = "USD"
    else:
        result["currency"] = "KRW"
    return result


def sell(ticker: str, market: str, qty: float) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    existing = repo.get_holding(ticker, market)
    if not existing:
        raise TradeError(f"{ticker}/{market} 보유 없음")
    if existing["qty"] < qty:
        raise TradeError(
            f"보유 수량 부족: 보유 {existing['qty']}주, 매도 요청 {qty}주"
        )

    price_native = _latest_price(ticker, market)
    price_krw, fx_rate = _to_krw(price_native, market)
    proceeds = price_krw * qty
    realized_pnl = (price_krw - existing["avg_price"]) * qty

    account = repo.get_account()
    repo.update_cash(account["cash"] + proceeds)

    new_qty = existing["qty"] - qty
    if new_qty < 1e-9:
        repo.delete_holding(ticker, market)
    else:
        repo.upsert_holding(ticker, market, new_qty, existing["avg_price"])

    repo.add_transaction(ticker, market, "SELL", qty, price_krw)

    result = {
        "ticker": ticker,
        "market": market,
        "side": "SELL",
        "qty": qty,
        "price": round(price_krw, 0),
        "price_native": round(price_native, 2),
        "proceeds": round(proceeds, 0),
        "realized_pnl": round(realized_pnl, 0),
        "avg_price": round(existing["avg_price"], 0),
        "new_qty": new_qty,
        "cash_after": round(account["cash"] + proceeds, 0),
    }
    if fx_rate:
        result["fx_rate"] = fx_rate
        result["currency"] = "USD"
    else:
        result["currency"] = "KRW"
    return result


def get_portfolio() -> dict:
    account = repo.get_account()
    holdings_raw = repo.get_holdings()

    fx_rate = _get_usd_krw()  # 현재 환율 (포트폴리오 평가에 사용)
    holdings = []
    total_value = 0.0

    for h in holdings_raw:
        try:
            price_native = _latest_price(h["ticker"], h["market"])
            price_krw, _ = _to_krw(price_native, h["market"])
        except Exception:
            price_krw = h["avg_price"]
            price_native = price_krw

        unrealized_pnl = (price_krw - h["avg_price"]) * h["qty"]
        position_value = price_krw * h["qty"]
        total_value += position_value

        item = {
            "ticker": h["ticker"],
            "market": h["market"],
            "qty": h["qty"],
            "avg_price": h["avg_price"],          # KRW
            "current_price": round(price_krw, 0), # KRW
            "position_value": round(position_value, 0),
            "unrealized_pnl": round(unrealized_pnl, 0),
            "pnl_pct": round((price_krw / h["avg_price"] - 1) * 100, 2)
                if h["avg_price"] > 0 else 0.0,
        }
        if h["market"] == "NASDAQ":
            item["current_price_usd"] = round(price_native, 2)
            item["currency"] = "USD"
        else:
            item["currency"] = "KRW"

        holdings.append(item)

    return {
        "cash": round(account["cash"], 0),
        "base_currency": "KRW",
        "fx_rate_usd": fx_rate,
        "holdings": holdings,
        "totals": {
            "positions_value": round(total_value, 0),
            "total_assets": round(account["cash"] + total_value, 0),
        },
    }
