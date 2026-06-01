import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # must run before app imports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.analyze import router as analyze_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.backtest import router as backtest_router  # noqa: E402
from app.api.catalyst import router as catalyst_router  # noqa: E402
from app.api.macro import router as macro_router  # noqa: E402
from app.api.news import router as news_router  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.screen import router as screen_router  # noqa: E402

app = FastAPI(title="StockScope API", version="0.1.0")

import os  # noqa: E402

_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
# Allow additional origins from env, e.g. ALLOWED_ORIGINS=https://my-app.vercel.app
_extra = os.environ.get("ALLOWED_ORIGINS", "")
for _o in _extra.split(","):
    _o = _o.strip()
    if _o:
        _ALLOWED_ORIGINS.append(_o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(analyze_router)
app.include_router(portfolio_router)
app.include_router(screen_router)
app.include_router(macro_router)
app.include_router(news_router)
app.include_router(backtest_router)
app.include_router(catalyst_router)


@app.on_event("startup")
def _startup() -> None:
    """서버 시작 시 DB 마이그레이션 실행."""
    try:
        from app.db.repo import migrate_add_realized_pnl
        migrate_add_realized_pnl()
        logging.getLogger(__name__).info("DB migration OK")
    except Exception as e:
        logging.getLogger(__name__).warning("DB migration warning: %s", e)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/debug/db")
def debug_db() -> dict:
    """DB 연결 상태 확인 (인증 불필요)."""
    import os
    db_url = os.environ.get("DATABASE_URL", "")
    result = {
        "db_type": "postgresql" if db_url else "sqlite",
        "db_url_set": bool(db_url),
        "db_url_prefix": db_url[:30] + "..." if db_url else None,
    }
    try:
        from app.db.connection import get_conn, fetchone
        import app.db.connection as conn_mod
        with get_conn() as con:
            row = fetchone(con, "SELECT COUNT(*) as cnt FROM users")
            result["connection"] = "ok"
            result["user_count"] = row["cnt"] if row else 0
            # 어떤 풀러 설정으로 연결됐는지 (비밀번호 제외)
            rc = conn_mod._resolved_conn
            if rc:
                result["resolved_host"] = rc.get("host")
                result["resolved_port"] = rc.get("port")
                result["resolved_user"] = rc.get("user")
    except Exception as e:
        result["connection"] = "error"
        result["error"] = str(e)
    return result
