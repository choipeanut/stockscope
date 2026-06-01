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
CREATE TABLE IF NOT EXISTS predictions (
    id            SERIAL PRIMARY KEY,
    strategy      TEXT NOT NULL,              -- 'catalyst' | 'momentum' | 'ml' ...
    ticker        TEXT NOT NULL,
    market        TEXT NOT NULL,
    name          TEXT,
    created_at    TEXT NOT NULL,              -- prediction timestamp (박제 시점)
    horizon_days  INTEGER NOT NULL,
    due_at        TEXT NOT NULL,              -- when to score it
    score         DOUBLE PRECISION,           -- strategy score at creation
    rank          INTEGER,                    -- rank within the batch
    thesis        TEXT,                       -- pre-registered reason
    entry_price   DOUBLE PRECISION,
    features      TEXT,                        -- JSON snapshot of inputs
    -- filled in at scoring time:
    scored_at     TEXT,
    exit_price    DOUBLE PRECISION,
    stock_return  DOUBLE PRECISION,
    bench_return  DOUBLE PRECISION,
    excess_return DOUBLE PRECISION,
    hit           INTEGER                      -- 1 if excess_return>0 else 0
);
CREATE INDEX IF NOT EXISTS idx_pred_due ON predictions(due_at, scored_at);
CREATE INDEX IF NOT EXISTS idx_pred_strategy ON predictions(strategy, created_at);
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
CREATE TABLE IF NOT EXISTS predictions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy      TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    market        TEXT NOT NULL,
    name          TEXT,
    created_at    TEXT NOT NULL,
    horizon_days  INTEGER NOT NULL,
    due_at        TEXT NOT NULL,
    score         REAL,
    rank          INTEGER,
    thesis        TEXT,
    entry_price   REAL,
    features      TEXT,
    scored_at     TEXT,
    exit_price    REAL,
    stock_return  REAL,
    bench_return  REAL,
    excess_return REAL,
    hit           INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pred_due ON predictions(due_at, scored_at);
CREATE INDEX IF NOT EXISTS idx_pred_strategy ON predictions(strategy, created_at);
"""


# 성공한 연결 설정 캐싱 (재탐색 방지)
_resolved_conn: dict | None = None

# Supabase 풀러 region 후보 (IPv4 지원). 순차 시도.
_SUPABASE_REGIONS = [
    "ap-northeast-2",  # Seoul
    "ap-northeast-1",  # Tokyo
    "ap-southeast-1",  # Singapore
    "us-east-1",
    "us-west-1",
    "us-east-2",
    "eu-central-1",
    "eu-west-1",
    "ap-southeast-2",  # Sydney
    "ap-south-1",      # Mumbai
    "sa-east-1",
]


def _extract_supabase_ref(hostname: str, username: str) -> str | None:
    """Supabase 프로젝트 ref 추출.
    direct:  db.{ref}.supabase.co
    pooler:  user = postgres.{ref}
    """
    if hostname and ".supabase.co" in hostname and hostname.startswith("db."):
        return hostname[len("db."):].split(".supabase.co")[0]
    if username and username.startswith("postgres."):
        return username.split("postgres.", 1)[1]
    return None


def _build_pooler_candidates(parsed, password: str) -> list[dict]:
    """프로젝트 ref로 여러 region 풀러 연결 설정 후보 생성."""
    ref = _extract_supabase_ref(parsed.hostname or "", parsed.username or "")
    if not ref:
        return []
    candidates = []
    for region in _SUPABASE_REGIONS:
        for prefix in ("aws-0", "aws-1"):
            candidates.append({
                "host": f"{prefix}-{region}.pooler.supabase.com",
                "port": 6543,  # transaction mode
                "dbname": "postgres",
                "user": f"postgres.{ref}",
                "password": password,
            })
    return candidates


def _try_connect(cfg: dict):
    """단일 설정으로 연결 시도 (IPv4 강제). 실패 시 None."""
    import socket
    import psycopg2
    import psycopg2.extras

    host = cfg["host"]
    # IPv4 강제 (Render 무료 플랜 IPv6 미지원)
    try:
        ipv4 = socket.getaddrinfo(host, cfg["port"], socket.AF_INET, socket.SOCK_STREAM)
        if ipv4:
            host = ipv4[0][4][0]
    except Exception:
        return None  # IPv4 resolve 실패 → 이 host는 건너뜀

    try:
        return psycopg2.connect(
            host=host,
            port=cfg["port"],
            dbname=cfg["dbname"],
            user=cfg["user"],
            password=cfg["password"],
            sslmode="require",
            connect_timeout=8,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    except Exception:
        return None


def _pg_conn():
    """psycopg2 연결 반환. 첫 호출 시 여러 풀러 region 자동 탐색 후 캐싱."""
    global _resolved_conn
    from urllib.parse import urlparse, unquote

    url = _DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    parsed = urlparse(url)
    password = unquote(parsed.password or "")

    # 이미 성공한 설정이 있으면 그것만 사용
    if _resolved_conn is not None:
        con = _try_connect(_resolved_conn)
        if con is not None:
            return con
        _resolved_conn = None  # 캐시 무효화 후 재탐색

    # 1) 사용자가 넣은 URL 그대로 시도 (이미 풀러 URL일 수 있음)
    direct_cfg = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") or "postgres",
        "user": parsed.username,
        "password": password,
    }
    con = _try_connect(direct_cfg)
    if con is not None:
        _resolved_conn = direct_cfg
        return con

    # 2) 여러 region 풀러 자동 시도
    for cfg in _build_pooler_candidates(parsed, password):
        con = _try_connect(cfg)
        if con is not None:
            _resolved_conn = cfg
            return con

    raise RuntimeError(
        "PostgreSQL 연결 실패: direct + 모든 풀러 region 시도 실패. "
        "DATABASE_URL 또는 비밀번호를 확인하세요."
    )


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
