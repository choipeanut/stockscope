"""Paper trading service — buy/sell at latest price, P&L tracking."""
from __future__ import annotations

from app.collectors.prices import get_ohlcv
from app.db import repo


class TradeError(ValueError):
    pass


def _latest_price(ticker: str, market: str) -> float:
    df = get_ohlcv(ticker, market, period_days=10)
    return float(df["close"].iloc[-1])


def buy(ticker: str, market: str, qty: float) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    price = _latest_price(ticker, market)
    cost = price * qty

    account = repo.get_account()
    if account["cash"] < cost:
        raise TradeError(
            f"Insufficient cash: need {cost:.2f}, have {account['cash']:.2f}"
        )

    # Update cash
    repo.update_cash(account["cash"] - cost)

    # Update holding (recompute avg_price)
    existing = repo.get_holding(ticker, market)
    if existing:
        old_qty = existing["qty"]
        old_avg = existing["avg_price"]
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + qty * price) / new_qty
    else:
        new_qty = qty
        new_avg = price

    repo.upsert_holding(ticker, market, new_qty, new_avg)
    repo.add_transaction(ticker, market, "BUY", qty, price)

    return {
        "ticker": ticker,
        "market": market,
        "side": "BUY",
        "qty": qty,
        "price": price,
        "cost": cost,
        "avg_price": new_avg,
        "new_qty": new_qty,
        "cash_remaining": account["cash"] - cost,
    }


def sell(ticker: str, market: str, qty: float) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    existing = repo.get_holding(ticker, market)
    if not existing:
        raise TradeError(f"No position in {ticker}/{market}")
    if existing["qty"] < qty:
        raise TradeError(
            f"Insufficient shares: have {existing['qty']}, want to sell {qty}"
        )

    price = _latest_price(ticker, market)
    proceeds = price * qty
    realized_pnl = (price - existing["avg_price"]) * qty

    # Update cash
    account = repo.get_account()
    repo.update_cash(account["cash"] + proceeds)

    # Update holding
    new_qty = existing["qty"] - qty
    if new_qty < 1e-9:
        repo.delete_holding(ticker, market)
    else:
        repo.upsert_holding(ticker, market, new_qty, existing["avg_price"])

    repo.add_transaction(ticker, market, "SELL", qty, price)

    return {
        "ticker": ticker,
        "market": market,
        "side": "SELL",
        "qty": qty,
        "price": price,
        "proceeds": proceeds,
        "realized_pnl": realized_pnl,
        "avg_price": existing["avg_price"],
        "new_qty": new_qty,
        "cash_after": account["cash"] + proceeds,
    }


def get_portfolio() -> dict:
    account = repo.get_account()
    holdings_raw = repo.get_holdings()

    holdings = []
    total_value = 0.0

    for h in holdings_raw:
        try:
            current_price = _latest_price(h["ticker"], h["market"])
        except Exception:
            current_price = h["avg_price"]  # fallback: cost basis

        unrealized_pnl = (current_price - h["avg_price"]) * h["qty"]
        position_value = current_price * h["qty"]
        total_value += position_value

        holdings.append({
            "ticker": h["ticker"],
            "market": h["market"],
            "qty": h["qty"],
            "avg_price": h["avg_price"],
            "current_price": current_price,
            "position_value": round(position_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct": round((current_price / h["avg_price"] - 1) * 100, 2)
            if h["avg_price"] > 0 else 0.0,
        })

    return {
        "cash": round(account["cash"], 2),
        "base_currency": account["base_currency"],
        "holdings": holdings,
        "totals": {
            "positions_value": round(total_value, 2),
            "total_assets": round(account["cash"] + total_value, 2),
        },
    }
