"""Paper trading service — buy/sell at latest price, P&L tracking."""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone

from app.collectors.company_name import get_company_name
from app.collectors.prices import get_ohlcv
from app.db import repo
from app.db.connection import get_conn, execute, fetchone

_fx_cache: dict = {}
_FX_TTL = 1800


class TradeError(ValueError):
    pass


def _get_usd_krw() -> float:
    now = time.time()
    if "rate" in _fx_cache and now - _fx_cache.get("ts", 0) < _FX_TTL:
        return _fx_cache["rate"]

    rate = None

    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="1d")
        if not hist.empty:
            r = float(hist["Close"].iloc[-1])
            if 900 < r < 2500:
                rate = round(r, 1)
    except Exception:
        pass

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
        rate = 1400.0

    _fx_cache["rate"] = rate
    _fx_cache["ts"] = now
    return rate


def _to_krw(price: float, market: str) -> tuple[float, float | None]:
    if market == "NASDAQ":
        fx = _get_usd_krw()
        return price * fx, fx
    return price, None


def _latest_price(ticker: str, market: str) -> float:
    df = get_ohlcv(ticker, market, period_days=10)
    return float(df["close"].iloc[-1])


def buy(ticker: str, market: str, qty: float, user_id: int) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    price_native = _latest_price(ticker, market)
    price_krw, fx_rate = _to_krw(price_native, market)
    cost = price_krw * qty
    ts = datetime.now(timezone.utc).isoformat()

    with get_conn() as con:
        # 계좌 조회 / 자동 생성
        acct = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))
        if acct is None:
            execute(con,
                "INSERT INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user_id, repo._INITIAL_CASH),
            )
            acct = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))

        if acct["cash"] < cost:
            raise TradeError(f"잔고 부족: 필요 {cost:,.0f}원, 보유 {acct['cash']:,.0f}원")

        existing = fetchone(con,
            "SELECT qty, avg_price FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )
        if existing:
            new_qty = existing["qty"] + qty
            new_avg = (existing["qty"] * existing["avg_price"] + qty * price_krw) / new_qty
        else:
            new_qty = qty
            new_avg = price_krw

        execute(con, "UPDATE account SET cash=? WHERE user_id=?",
                (acct["cash"] - cost, user_id))
        execute(con,
            """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, ticker, market)
               DO UPDATE SET qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price""",
            (user_id, ticker, market, new_qty, new_avg),
        )
        execute(con,
            "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user_id, ts, ticker, market, "BUY", qty, price_krw, 0.0),
        )

    result = {
        "ticker": ticker, "market": market, "side": "BUY",
        "qty": qty, "price": round(price_krw, 0),
        "price_native": round(price_native, 2),
        "cost": round(cost, 0), "avg_price": round(new_avg, 0),
        "new_qty": new_qty, "cash_remaining": round(acct["cash"] - cost, 0),
    }
    if fx_rate:
        result["fx_rate"] = fx_rate
        result["currency"] = "USD"
    else:
        result["currency"] = "KRW"
    return result


def sell(ticker: str, market: str, qty: float, user_id: int) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    price_native = _latest_price(ticker, market)
    price_krw, fx_rate = _to_krw(price_native, market)
    ts = datetime.now(timezone.utc).isoformat()

    with get_conn() as con:
        existing = fetchone(con,
            "SELECT qty, avg_price FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )
        if not existing:
            raise TradeError(f"{ticker}/{market} 보유 없음")
        if existing["qty"] < qty - 1e-9:
            raise TradeError(f"보유 수량 부족: 보유 {existing['qty']}주, 매도 요청 {qty}주")

        proceeds = price_krw * qty
        realized_pnl = (price_krw - existing["avg_price"]) * qty

        acct = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))
        if acct is None:
            execute(con,
                "INSERT INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user_id, repo._INITIAL_CASH),
            )
            acct = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))

        execute(con, "UPDATE account SET cash=? WHERE user_id=?",
                (acct["cash"] + proceeds, user_id))

        new_qty = existing["qty"] - qty
        if new_qty < 1e-9:
            execute(con,
                "DELETE FROM holdings WHERE user_id=? AND ticker=? AND market=?",
                (user_id, ticker, market),
            )
        else:
            execute(con,
                """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id, ticker, market)
                   DO UPDATE SET qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price""",
                (user_id, ticker, market, new_qty, existing["avg_price"]),
            )

        execute(con,
            "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user_id, ts, ticker, market, "SELL", qty, price_krw, realized_pnl),
        )

    result = {
        "ticker": ticker, "market": market, "side": "SELL",
        "qty": qty, "price": round(price_krw, 0),
        "price_native": round(price_native, 2),
        "proceeds": round(proceeds, 0),
        "realized_pnl": round(realized_pnl, 0),
        "avg_price": round(existing["avg_price"], 0),
        "new_qty": new_qty, "cash_after": round(acct["cash"] + proceeds, 0),
    }
    if fx_rate:
        result["fx_rate"] = fx_rate
        result["currency"] = "USD"
    else:
        result["currency"] = "KRW"
    return result


def get_portfolio(user_id: int) -> dict:
    account = repo.get_account(user_id)
    holdings_raw = repo.get_holdings(user_id)

    fx_rate = _get_usd_krw()
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
            "name": get_company_name(h["ticker"], h["market"]),
            "qty": h["qty"],
            "avg_price": h["avg_price"],
            "current_price": round(price_krw, 0),
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

    realized_pnl_total = repo.get_realized_pnl(user_id)

    return {
        "cash": round(account["cash"], 0),
        "base_currency": "KRW",
        "fx_rate_usd": fx_rate,
        "holdings": holdings,
        "totals": {
            "positions_value": round(total_value, 0),
            "total_assets": round(account["cash"] + total_value, 0),
            "unrealized_pnl": round(sum(h["unrealized_pnl"] for h in holdings), 0),
            "realized_pnl": round(realized_pnl_total, 0),
        },
    }
