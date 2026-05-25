"""Portfolio and trade API routes — M3."""
from __future__ import annotations

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
