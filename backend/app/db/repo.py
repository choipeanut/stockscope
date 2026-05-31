"""Repository — SQLite(로컬) / PostgreSQL(프로덕션) 듀얼 지원."""
from __future__ import annotations

from datetime import datetime, timezone
from app.db.connection import get_conn, execute, fetchone, fetchall, adapt_sql

_INITIAL_CASH = 10_000_000.0  # 가상 초기 현금 (KRW)


# ── Users ──────────────────────────────────────────────────────────────────

def upsert_user(google_sub: str, email: str, name: str, picture: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as con:
        execute(con,
            """INSERT INTO users (google_sub, email, name, picture, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(google_sub)
               DO UPDATE SET email=EXCLUDED.email, name=EXCLUDED.name, picture=EXCLUDED.picture""",
            (google_sub, email, name, picture, now),
        )
        user = fetchone(con, "SELECT * FROM users WHERE google_sub=?", (google_sub,))
        # 계좌 없으면 생성
        existing = fetchone(con, "SELECT id FROM account WHERE user_id=?", (user["id"],))
        if not existing:
            execute(con,
                "INSERT INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user["id"], _INITIAL_CASH),
            )
    return user


def get_user_by_id(user_id: int) -> dict | None:
    with get_conn() as con:
        return fetchone(con, "SELECT * FROM users WHERE id=?", (user_id,))


# ── Account ────────────────────────────────────────────────────────────────

def get_account(user_id: int) -> dict:
    with get_conn() as con:
        row = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))
        if not row:
            execute(con,
                "INSERT INTO account (user_id, cash, base_currency) VALUES (?,?,'MULTI')",
                (user_id, _INITIAL_CASH),
            )
            row = fetchone(con, "SELECT * FROM account WHERE user_id=?", (user_id,))
        return row


def update_cash(user_id: int, new_cash: float) -> None:
    with get_conn() as con:
        execute(con, "UPDATE account SET cash=? WHERE user_id=?", (new_cash, user_id))


# ── Holdings ───────────────────────────────────────────────────────────────

def get_holdings(user_id: int) -> list[dict]:
    with get_conn() as con:
        return fetchall(con, "SELECT * FROM holdings WHERE user_id=?", (user_id,))


def get_holding(user_id: int, ticker: str, market: str) -> dict | None:
    with get_conn() as con:
        return fetchone(con,
            "SELECT * FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )


def upsert_holding(user_id: int, ticker: str, market: str, qty: float, avg_price: float) -> None:
    with get_conn() as con:
        execute(con,
            """INSERT INTO holdings (user_id, ticker, market, qty, avg_price)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, ticker, market)
               DO UPDATE SET qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price""",
            (user_id, ticker, market, qty, avg_price),
        )


def delete_holding(user_id: int, ticker: str, market: str) -> None:
    with get_conn() as con:
        execute(con,
            "DELETE FROM holdings WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )


# ── Transactions ───────────────────────────────────────────────────────────

def add_transaction(user_id: int, ticker: str, market: str, side: str,
                    qty: float, price: float, realized_pnl: float = 0.0) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with get_conn() as con:
        execute(con,
            "INSERT INTO transactions (user_id, ts, ticker, market, side, qty, price, realized_pnl)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user_id, ts, ticker, market, side, qty, price, realized_pnl),
        )


def get_transactions(user_id: int, limit: int = 100) -> list[dict]:
    with get_conn() as con:
        return fetchall(con,
            "SELECT * FROM transactions WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )


def get_realized_pnl(user_id: int) -> float:
    with get_conn() as con:
        row = fetchone(con,
            "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM transactions WHERE user_id=?",
            (user_id,),
        )
    return float(row["total"]) if row else 0.0


def get_first_buy_ts(user_id: int, ticker: str, market: str) -> str | None:
    """해당 종목의 첫 매수 시점(ISO 문자열) 반환."""
    with get_conn() as con:
        row = fetchone(con,
            "SELECT MIN(ts) as first_ts FROM transactions"
            " WHERE user_id=? AND ticker=? AND market=? AND side='BUY'",
            (user_id, ticker, market),
        )
    return row["first_ts"] if row and row.get("first_ts") else None


def migrate_add_realized_pnl() -> None:
    """기존 DB에 realized_pnl 컬럼 없으면 추가 (SQLite 전용 — PG는 스키마에 이미 포함)."""
    from app.db.connection import is_postgres
    if is_postgres():
        return  # PostgreSQL은 스키마 생성 시 이미 포함
    from app.db.connection import get_conn as _gc
    import sqlite3
    from app.db.connection import _SQLITE_PATH, SQLITE_SCHEMA
    con = sqlite3.connect(str(_SQLITE_PATH))
    try:
        con.executescript(SQLITE_SCHEMA)
        cols = [r[1] for r in con.execute("PRAGMA table_info(transactions)").fetchall()]
        if "realized_pnl" not in cols:
            con.execute("ALTER TABLE transactions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0")
            con.commit()
    finally:
        con.close()


# ── Watchlist ──────────────────────────────────────────────────────────────

def add_watchlist(user_id: int, ticker: str, market: str) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    with get_conn() as con:
        execute(con,
            "INSERT INTO watchlist (user_id, ticker, market, added_ts) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id, ticker, market) DO NOTHING",
            (user_id, ticker, market, ts),
        )
        return fetchone(con,
            "SELECT * FROM watchlist WHERE user_id=? AND ticker=? AND market=?",
            (user_id, ticker, market),
        )


def get_watchlist(user_id: int) -> list[dict]:
    with get_conn() as con:
        return fetchall(con,
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY added_ts DESC",
            (user_id,),
        )


def delete_watchlist(user_id: int, wid: int) -> None:
    with get_conn() as con:
        execute(con,
            "DELETE FROM watchlist WHERE id=? AND user_id=?", (wid, user_id)
        )
