"""Paper trading service — buy/sell at latest price, P&L tracking.

모든 금액은 KRW 기준으로 저장.
NASDAQ 종목: USD 가격 × USD/KRW 환율로 변환 후 저장.
"""
from __future__ import annotations

import json
import time
import urllib.request

import sqlite3

from app.collectors.company_name import get_company_name
from app.collectors.prices import get_ohlcv
from app.db import repo
from app.db.repo import _DB_PATH, _SCHEMA

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


def _atomic_conn() -> sqlite3.Connection:
    """단일 원자적 트랜잭션용 커넥션 반환."""
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    repo.migrate_add_realized_pnl.__wrapped__(con) if hasattr(repo.migrate_add_realized_pnl, "__wrapped__") else None
    return con


def buy(ticker: str, market: str, qty: float, user_id: int) -> dict:
    if qty <= 0:
        raise TradeError("qty must be positive")

    price_native = _latest_price(ticker, market)
    price_krw, fx_rate = _to_krw(price_native, market)
    cost = price_krw * qty
    ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    # 단일 DB 트랜잭션으로 원자성 보장
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript("PRAGMA foreign_keys = OFF;" + _SCHEMA)  # FK 비활성화 후 테이블 생성
    try:
        with con:
            # account 없으면 자동 복구
            acct_row = con.execute(
                "SELECT cash FROM account WHERE user_id=?", (user_id,)
            ).fetchone()
            if acct_row is None:
                con.execute(
                    "INSERT OR REPLACE INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                    (user_id, repo._INITIAL_CASH),
                )
                acct_row = con.execute(
                    "SELECT cash FROM account WHERE user_id=?", (user_id,)
                ).fetchone()
            if acct_row is None:
                raise TradeError(f"계좌 초기화 실패: user_id={user_id}. 다시 로그인해주세요.")
            acct = dict(acct_row)

            if acct["cash"] < cost:
                raise TradeError(
                    f"잔고 부족: 필요 {cost:,.0f}원, 보유 {acct['cash']:,.0f}원"
                )

            existing = con.execute(
                "SELECT qty, avg_price FROM holdings WHERE user_id=? AND ticker=? AND market=?",
                (user_id, ticker, market),
            ).fetchone()

            if existing:
                old_qty = existing["qty"]
                old_avg = existing["avg_price"]
                new_qty = old_qty + qty
                new_avg = (old_qty * old_avg + qty * price_krw) / new_qty
            else:
                new_qty = qty
                new_avg = price_krw

            con.execute(
                "UPDATE account SET cash=? WHERE user_id=?",
                (acct["cash"] - cost, user_id),
            )
            con.execute(
                """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id, ticker, market)
                   DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price""",
                (user_id, ticker, market, new_qty, new_avg),
            )
            con.execute(
                "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user_id, ts, ticker, market, "BUY", qty, price_krw, 0.0),
            )
    finally:
        con.close()

    result = {
        "ticker": ticker,
        "market": market,
        "side": "BUY",
        "qty": qty,
        "price": round(price_krw, 0),
        "price_native": round(price_native, 2),
        "cost": round(cost, 0),
        "avg_price": round(new_avg, 0),
        "new_qty": new_qty,
        "cash_remaining": round(acct["cash"] - cost, 0),
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
    ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript("PRAGMA foreign_keys = OFF;" + _SCHEMA)  # FK 비활성화 후 테이블 생성
    try:
        with con:
            existing = con.execute(
                "SELECT qty, avg_price FROM holdings WHERE user_id=? AND ticker=? AND market=?",
                (user_id, ticker, market),
            ).fetchone()
            if not existing:
                raise TradeError(f"{ticker}/{market} 보유 없음")
            if existing["qty"] < qty - 1e-9:
                raise TradeError(
                    f"보유 수량 부족: 보유 {existing['qty']}주, 매도 요청 {qty}주"
                )

            proceeds = price_krw * qty
            realized_pnl = (price_krw - existing["avg_price"]) * qty

            acct_row = con.execute(
                "SELECT cash FROM account WHERE user_id=?", (user_id,)
            ).fetchone()
            if acct_row is None:
                con.execute(
                    "INSERT OR REPLACE INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                    (user_id, repo._INITIAL_CASH),
                )
                acct_row = con.execute(
                    "SELECT cash FROM account WHERE user_id=?", (user_id,)
                ).fetchone()
            if acct_row is None:
                raise TradeError(f"계좌 초기화 실패: user_id={user_id}. 다시 로그인해주세요.")
            acct = dict(acct_row)

            con.execute(
                "UPDATE account SET cash=? WHERE user_id=?",
                (acct["cash"] + proceeds, user_id),
            )

            new_qty = existing["qty"] - qty
            if new_qty < 1e-9:
                con.execute(
                    "DELETE FROM holdings WHERE user_id=? AND ticker=? AND market=?",
                    (user_id, ticker, market),
                )
            else:
                con.execute(
                    """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(user_id, ticker, market)
                       DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price""",
                    (user_id, ticker, market, new_qty, existing["avg_price"]),
                )

            con.execute(
                "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user_id, ts, ticker, market, "SELL", qty, price_krw, realized_pnl),
            )
    finally:
        con.close()

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
        "cash_after": round(acct["cash"] + proceeds, 0),
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
