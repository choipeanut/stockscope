"""Portfolio and trade API routes — M3."""
from __future__ import annotations

import json
import time
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import repo
from app.services.paper_trading import TradeError, buy, get_portfolio, sell

router = APIRouter()


class TradeRequest(BaseModel):
    side: str         # BUY | SELL
    ticker: str
    market: str
    qty: float


@router.post("/trade")
def trade(req: TradeRequest) -> dict:
    side = req.side.upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    try:
        if side == "BUY":
            result = buy(req.ticker.upper(), req.market.upper(), req.qty)
        else:
            result = sell(req.ticker.upper(), req.market.upper(), req.qty)
    except TradeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.get("/portfolio")
def portfolio() -> dict:
    return get_portfolio()


@router.get("/debug/fx")
def debug_fx() -> dict:
    """FX rate debug — 각 메서드별 결과 반환."""
    results = {}

    # Method 1: yfinance history
    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not hist.empty:
            r = float(hist["Close"].iloc[-1])
            results["yfinance_history"] = r
        else:
            results["yfinance_history"] = "empty_df"
    except Exception as e:
        results["yfinance_history"] = f"error: {e}"

    # Method 2: fawazahmed0 CDN
    try:
        url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            r = data.get("usd", {}).get("krw")
            results["fawazahmed0"] = r
    except Exception as e:
        results["fawazahmed0"] = f"error: {e}"

    # Method 3: exchangerate-api
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            r = data.get("rates", {}).get("KRW")
            results["exchangerate_api"] = r
    except Exception as e:
        results["exchangerate_api"] = f"error: {e}"

    # Current cached value
    from app.services import paper_trading as pt
    results["cached_rate"] = pt._fx_cache.get("rate")
    results["cache_age_sec"] = round(time.time() - pt._fx_cache.get("ts", 0), 1) if "ts" in pt._fx_cache else None

    return results


@router.get("/transactions")
def transactions(limit: int = 50) -> dict:
    return {"transactions": repo.get_transactions(limit)}


@router.post("/watchlist")
def add_watchlist(ticker: str, market: str) -> dict:
    return repo.add_watchlist(ticker.upper(), market.upper())


@router.get("/watchlist")
def get_watchlist() -> dict:
    return {"watchlist": repo.get_watchlist()}


@router.delete("/watchlist/{wid}")
def delete_watchlist(wid: int) -> dict:
    repo.delete_watchlist(wid)
    return {"deleted": wid}
