"""DB connection factory — SQLite (로컬) / PostgreSQL (프로덕션).

DATABASE_URL 환경변수가 있으면 PostgreSQL, 없으면 SQLite.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_IS_PG = bool(_DATABASE_URL)

# SQLite 경로 (로컬 개발용)
_SQLITE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "portfolio.db"
if not _IS_PG:
    _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)


def is_postgres() -> bool:
    return _IS_PG


# ── PostgreSQL 스키마 (SQLite와 거의 동일, AUTOINCREMENT→SERIAL, ? → %s) ──
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    google_sub  TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,
    picture     TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED,
    cash          DOUBLE PRECISION NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'MULTI'
);
CREATE TABLE IF NOT EXISTS holdings (
    id        SERIAL PRIMARY KEY,
    user_id   INTEGER NOT NULL,
    ticker    TEXT NOT NULL,
    market    TEXT NOT NULL,
    qty       DOUBLE PRECISION NOT NULL,
    avg_price DOUBLE PRECISION NOT NULL,
    UNIQUE(user_id, ticker, market)
);
CREATE TABLE IF NOT EXISTS transactions (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    ts           TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    market       TEXT NOT NULL,
    side         TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    qty          DOUBLE PRECISION NOT NULL,
    price        DOUBLE PRECISION NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watchlist (
    id       SERIAL PRIMARY KEY,
    user_id  INTEGER NOT NULL,
    ticker   TEXT NOT NULL,
    market   TEXT NOT NULL,
    added_ts TEXT NOT NULL,
    UNIQUE(user_id, ticker, market)
);
"""

# SQLite 스키마
SQLITE_SCHEMA = """
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
    user_id       INTEGER NOT NULL UNIQUE,
    cash          REAL NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'MULTI'
);
CREATE TABLE IF NOT EXISTS holdings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    ticker    TEXT NOT NULL,
    market    TEXT NOT NULL,
    qty       REAL NOT NULL,
    avg_price REAL NOT NULL,
    UNIQUE(user_id, ticker, market)
);
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
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
    user_id  INTEGER NOT NULL,
    ticker   TEXT NOT NULL,
    market   TEXT NOT NULL,
    added_ts TEXT NOT NULL,
    UNIQUE(user_id, ticker, market)
);
"""


def _pg_conn():
    """psycopg2 연결 반환 (IPv4 강제 + Supabase SSL)."""
    import socket
    import psycopg2
    import psycopg2.extras
    from urllib.parse import urlparse, unquote

    url = _DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or 5432

    # IPv4 주소로 강제 변환 (Render 무료 플랜 IPv6 미지원 우회)
    try:
        ipv4_list = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
        if ipv4_list:
            hostname = ipv4_list[0][4][0]
    except Exception:
        pass  # 실패 시 원래 hostname 사용

    con = psycopg2.connect(
        host=hostname,
        port=port,
        dbname=parsed.path.lstrip("/"),
        user=parsed.username,
        password=unquote(parsed.password or ""),
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return con


def _sqlite_conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(_SQLITE_PATH))
    con.row_factory = sqlite3.Row
    return con


def _init_schema(con) -> None:
    """테이블 없으면 생성."""
    if _IS_PG:
        cur = con.cursor()
        for stmt in PG_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        con.commit()
        cur.close()
    else:
        con.executescript(SQLITE_SCHEMA)


def adapt_sql(sql: str) -> str:
    """SQLite ? 파라미터를 PostgreSQL %s로 변환."""
    if _IS_PG:
        return sql.replace("?", "%s")
    return sql


def row_to_dict(row) -> dict | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)  # sqlite3.Row도 dict()로 변환 가능


@contextmanager
def get_conn():
    """컨텍스트 매니저: 연결 획득 → 커밋/롤백 → 닫기."""
    if _IS_PG:
        con = _pg_conn()
    else:
        con = _sqlite_conn()
    _init_schema(con)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def execute(con, sql: str, params: tuple = ()) -> Any:
    """단일 쿼리 실행."""
    sql = adapt_sql(sql)
    if _IS_PG:
        cur = con.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return con.execute(sql, params)


def fetchone(con, sql: str, params: tuple = ()) -> dict | None:
    sql = adapt_sql(sql)
    if _IS_PG:
        cur = con.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    else:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None


def fetchall(con, sql: str, params: tuple = ()) -> list[dict]:
    sql = adapt_sql(sql)
    if _IS_PG:
        cur = con.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    else:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
