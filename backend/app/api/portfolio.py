"""Portfolio and trade API routes — M3."""
from __future__ import annotations

import json
import time
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth_dep import get_current_user
from app.db import repo
from app.services.paper_trading import TradeError, buy, get_portfolio, sell

router = APIRouter()


class TradeRequest(BaseModel):
    side: str         # BUY | SELL
    ticker: str
    market: str
    qty: float


@router.post("/trade")
def trade(req: TradeRequest, user: dict = Depends(get_current_user)) -> dict:
    side = req.side.upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    try:
        if side == "BUY":
            result = buy(req.ticker.upper(), req.market.upper(), req.qty, user["user_id"])
        else:
            result = sell(req.ticker.upper(), req.market.upper(), req.qty, user["user_id"])
    except TradeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.get("/portfolio")
def portfolio(user: dict = Depends(get_current_user)) -> dict:
    return get_portfolio(user["user_id"])


@router.get("/transactions")
def transactions(limit: int = 50, user: dict = Depends(get_current_user)) -> dict:
    return {"transactions": repo.get_transactions(user["user_id"], limit)}


@router.get("/prices")
def prices(
    ticker: str,
    market: str,
    days: int = 365,
    user: dict = Depends(get_current_user),
) -> dict:
    """가벼운 OHLCV 조회 — 포트폴리오 차트용 (팩터 계산 없음)."""
    from app.collectors.prices import get_ohlcv
    market = market.upper()
    try:
        df = get_ohlcv(ticker.upper(), market, period_days=days)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"가격 조회 실패: {e}")
    records = df.tail(days).copy()
    records["date"] = records["date"].astype(str)
    ohlcv = records[["date", "open", "high", "low", "close", "volume"]].to_dict(
        orient="records"
    )
    return {"ticker": ticker.upper(), "market": market, "ohlcv": ohlcv}


@router.post("/watchlist")
def add_watchlist(ticker: str, market: str, user: dict = Depends(get_current_user)) -> dict:
    return repo.add_watchlist(user["user_id"], ticker.upper(), market.upper())


@router.get("/watchlist")
def get_watchlist(user: dict = Depends(get_current_user)) -> dict:
    return {"watchlist": repo.get_watchlist(user["user_id"])}


@router.delete("/watchlist/{wid}")
def delete_watchlist(wid: int, user: dict = Depends(get_current_user)) -> dict:
    repo.delete_watchlist(user["user_id"], wid)
    return {"deleted": wid}


# ── Debug endpoints ───────────────────────────────────────────────────────────

@router.get("/debug/fx")
def debug_fx() -> dict:
    """FX rate debug — 각 메서드별 결과 반환 (인증 불필요)."""
    results: dict = {}

    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not hist.empty:
            results["yfinance_history"] = float(hist["Close"].iloc[-1])
        else:
            results["yfinance_history"] = "empty_df"
    except Exception as e:
        results["yfinance_history"] = f"error: {e}"

    try:
        url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            results["fawazahmed0"] = data.get("usd", {}).get("krw")
    except Exception as e:
        results["fawazahmed0"] = f"error: {e}"

    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            results["exchangerate_api"] = data.get("rates", {}).get("KRW")
    except Exception as e:
        results["exchangerate_api"] = f"error: {e}"

    from app.services import paper_trading as pt
    results["cached_rate"] = pt._fx_cache.get("rate")
    results["cache_age_sec"] = (
        round(time.time() - pt._fx_cache.get("ts", 0), 1)
        if "ts" in pt._fx_cache else None
    )
    return results
