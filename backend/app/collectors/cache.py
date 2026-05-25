"""SQLite-backed TTL cache for external API responses."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "cache.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    as_of TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB_PATH))
    con.execute(_CREATE_SQL)
    con.commit()
    return con


def get(key: str) -> tuple[Any, str] | None:
    """Return (parsed_payload, as_of) if cached and not expired, else None."""
    with _conn() as con:
        row = con.execute(
            "SELECT payload, as_of, ttl_seconds FROM cache WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    payload_str, as_of_str, ttl = row
    as_of = datetime.fromisoformat(as_of_str)
    age = (datetime.now(timezone.utc) - as_of).total_seconds()
    if age > ttl:
        return None
    return json.loads(payload_str), as_of_str


def set(key: str, value: Any, ttl_seconds: int) -> str:
    """Serialize and store value; return as_of ISO string."""
    as_of = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache (key, payload, as_of, ttl_seconds) VALUES (?,?,?,?)",
            (key, json.dumps(value), as_of, ttl_seconds),
        )
        con.commit()
    return as_of
