"""SQLite repository — users, account, holdings, transactions, watchlist.

모든 포트폴리오 데이터는 user_id로 격리.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "portfolio.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub  TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,
    picture     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users(id),
    cash          REAL NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'MULTI'
);

CREATE TABLE IF NOT EXISTS holdings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    ticker    TEXT NOT NULL,
    market    TEXT NOT NULL,
    qty       REAL NOT NULL,
    avg_price REAL NOT NULL,
    UNIQUE(user_id, ticker, market)
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    ts           TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    market       TEXT NOT NULL,
    side         TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    qty          REAL NOT NULL,
    price        REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlist (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    ticker   TEXT NOT NULL,
    market   TEXT NOT NULL,
    added_ts TEXT NOT NULL,
    UNIQUE(user_id, ticker, market)
);
"""

_INITIAL_CASH = 10_000_000.0  # KRW-equivalent virtual cash per user


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


# ── Users ─────────────────────────────────────────────────────────────────────

def upsert_user(google_sub: str, email: str, name: str, picture: str) -> dict:
    """Google 로그인 시 유저 생성 또는 업데이트. 신규 유저면 계좌도 생성."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            """INSERT INTO users (google_sub, email, name, picture, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(google_sub)
               DO UPDATE SET email=excluded.email, name=excluded.name, picture=excluded.picture""",
            (google_sub, email, name, picture, now),
        )
        con.commit()
        user = dict(con.execute(
            "SELECT * FROM users WHERE google_sub=?", (google_sub,)
        ).fetchone())

        # 계좌가 없으면 초기 가상 현금으로 생성
        existing = con.execute(
            "SELECT id FROM account WHERE user_id=?", (user["id"],)
        ).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user["id"], _INITIAL_CASH),
            )
            con.commit()

    return user


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


# ── Account ───────────────────────────────────────────────────────────────────

def get_account(user_id: int) -> dict:
    """계좌 조회. 없으면 초기 잔고로 자동 생성 (복구용)."""
    con = sqlite3.connect(str(_DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript("PRAGMA foreign_keys = OFF;" + _SCHEMA)  # FK 비활성화 — user 레코드 없어도 account 생성 가능
    try:
        row = con.execute(
            "SELECT * FROM account WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            con.execute(
                "INSERT OR REPLACE INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user_id, _INITIAL_CASH),
            )
            con.commit()
            row = con.execute(
                "SELECT * FROM account WHERE user_id=?", (user_id,)
            ).fetchone()
        return dict(row)
    finally:
        con.close()


def update_cash(user_id: int, new_cash: float) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE account SET cash=? WHERE user_id=?", (new_cash, user_id)
        )
        con.commit()


# ── Holdings ──────────────────────────────────────────────────────────────────

def get_holdings(user_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM holdings WHERE user_id=?", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_holding(user_id: int, ticker: str, market: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        ).fetchone()
    return dict(row) if row else None


def upsert_holding(user_id: int, ticker: str, market: str, qty: float, avg_price: float) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, ticker, market)
               DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price""",
            (user_id, ticker, market, qty, avg_price),
        )
        con.commit()


def delete_holding(user_id: int, ticker: str, market: str) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )
        con.commit()


# ── Transactions ──────────────────────────────────────────────────────────────

def add_transaction(
    user_id: int, ticker: str, market: str, side: str,
    qty: float, price: float, realized_pnl: float = 0.0,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user_id, ts, ticker, market, side, qty, price, realized_pnl),
        )
        con.commit()


def get_transactions(user_id: int, limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_realized_pnl(user_id: int) -> float:
    """유저의 누적 실현손익 합계 반환."""
    with _conn() as con:
        row = con.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM transactions WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return float(row["total"]) if row else 0.0


def migrate_add_realized_pnl() -> None:
    """기존 DB에 realized_pnl 컬럼이 없으면 추가 (안전한 마이그레이션)."""
    with _conn() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(transactions)").fetchall()]
        if "realized_pnl" not in cols:
            con.execute("ALTER TABLE transactions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0")
            con.commit()


# ── Watchlist ─────────────────────────────────────────────────────────────────

def add_watchlist(user_id: int, ticker: str, market: str) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, ticker, market, added_ts) VALUES (?,?,?,?)",
            (user_id, ticker, market, ts),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM watchlist WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        ).fetchone()
    return dict(row)


def get_watchlist(user_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY added_ts DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_watchlist(user_id: int, wid: int) -> None:
    with _conn() as con:
        # 본인 항목만 삭제
        con.execute(
            "DELETE FROM watchlist WHERE id=? AND user_id=?", (wid, user_id)
        )
        con.commit()
