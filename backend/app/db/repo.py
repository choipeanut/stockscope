"""SQLite repository — account, holdings, transactions, watchlist."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "portfolio.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY,
    cash REAL NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'MULTI'
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_price REAL NOT NULL,
    UNIQUE(ticker, market)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    qty REAL NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    added_ts TEXT NOT NULL,
    UNIQUE(ticker, market)
);
"""

_INITIAL_CASH = 10_000_000.0  # KRW-equivalent virtual cash


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    # Seed account if empty
    if con.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO account (id, cash, base_currency) VALUES (1, ?, 'MULTI')",
            (_INITIAL_CASH,),
        )
        con.commit()
    return con


# ── Account ──────────────────────────────────────────────────────────────────

def get_account() -> dict:
    with _conn() as con:
        row = con.execute("SELECT * FROM account WHERE id = 1").fetchone()
    return dict(row)


def update_cash(new_cash: float) -> None:
    with _conn() as con:
        con.execute("UPDATE account SET cash = ? WHERE id = 1", (new_cash,))
        con.commit()


# ── Holdings ─────────────────────────────────────────────────────────────────

def get_holdings() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM holdings").fetchall()
    return [dict(r) for r in rows]


def get_holding(ticker: str, market: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM holdings WHERE ticker=? AND market=?", (ticker, market)
        ).fetchone()
    return dict(row) if row else None


def upsert_holding(ticker: str, market: str, qty: float, avg_price: float) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO holdings (ticker, market, qty, avg_price)
               VALUES (?,?,?,?)
               ON CONFLICT(ticker, market)
               DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price""",
            (ticker, market, qty, avg_price),
        )
        con.commit()


def delete_holding(ticker: str, market: str) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM holdings WHERE ticker=? AND market=?", (ticker, market)
        )
        con.commit()


# ── Transactions ─────────────────────────────────────────────────────────────

def add_transaction(ticker: str, market: str, side: str, qty: float, price: float) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO transactions (ts, ticker, market, side, qty, price) VALUES (?,?,?,?,?,?)",
            (ts, ticker, market, side, qty, price),
        )
        con.commit()


def get_transactions(limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM transactions ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Watchlist ─────────────────────────────────────────────────────────────────

def add_watchlist(ticker: str, market: str) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, market, added_ts) VALUES (?,?,?)",
            (ticker, market, ts),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM watchlist WHERE ticker=? AND market=?", (ticker, market)
        ).fetchone()
    return dict(row)


def get_watchlist() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM watchlist ORDER BY added_ts DESC").fetchall()
    return [dict(r) for r in rows]


def delete_watchlist(wid: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM watchlist WHERE id=?", (wid,))
        con.commit()
