import logging
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # must run before app imports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Benign numpy noise: averaging an all-NaN feature window (e.g. a short price
# slice during dataset build) returns NaN, which is imputed downstream. Silence
# just this one message so it doesn't drown the logs — without hiding others.
warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)

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


@app.get("/debug/newsapi")
def debug_newsapi() -> dict:
    """전체 시장 환경 파이프라인 라이브 점검 (인증 불필요).

    NEWSAPI_KEY 유효성(401) vs 할당량(429) vs 기사 0개 vs 정상 을 구분해서
    실제 응답을 그대로 보여준다. → '전체 시장 환경'이 왜 안 뜨는지 확정용.
    """
    import os
    import requests as _rq

    out: dict = {}
    news_key = os.environ.get("NEWSAPI_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    out["newsapi_key_set"] = bool(news_key)
    out["newsapi_key_len"] = len(news_key)
    out["anthropic_key_set"] = bool(anthropic_key)

    # 1) NewsAPI 원시 호출 (1회) — 상태코드/메시지/기사수 그대로
    if news_key:
        try:
            from datetime import datetime, timedelta, timezone
            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = _rq.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": "Federal Reserve interest rate inflation economy",
                    "language": "en", "sortBy": "publishedAt",
                    "pageSize": 5, "from": since, "apiKey": news_key,
                },
                timeout=10,
            )
            out["newsapi_status"] = resp.status_code
            try:
                body = resp.json()
            except Exception:
                body = {}
            out["newsapi_api_status"] = body.get("status")       # "ok" | "error"
            out["newsapi_code"] = body.get("code")               # e.g. apiKeyInvalid, rateLimited
            out["newsapi_message"] = body.get("message")
            out["newsapi_total_results"] = body.get("totalResults")
            arts = body.get("articles", []) or []
            out["newsapi_article_count"] = len(arts)
            out["newsapi_sample_title"] = arts[0].get("title") if arts else None
        except Exception as e:
            out["newsapi_status"] = "exception"
            out["newsapi_error"] = str(e)

    # 2) 우리 수집 함수 결과 + 캐시 상태
    try:
        from app.collectors import news_macro
        news = news_macro.get_global_market_news(limit_per_category=4)
        out["collector_global_news_count"] = len(news)
        out["collector_last_error"] = news_macro.last_newsapi_error()
        entry = news_macro._global_cache.get("entry")
        out["collector_cache_age_sec"] = (
            round(__import__("time").time() - entry["ts"]) if entry else None
        )
    except Exception as e:
        out["collector_error"] = str(e)

    # 3) 시장 감성 분석 결과 (available 여부 + reason)
    try:
        from app.services.macro_sentiment import analyze_market_sentiment
        ms = analyze_market_sentiment(out.get("collector_global_news_count") and news or [])
        out["market_sentiment_available"] = ms.get("available")
        out["market_sentiment_reason"] = ms.get("reason")
        out["market_sentiment_score"] = ms.get("market_score")
    except Exception as e:
        out["market_sentiment_error"] = str(e)

    return out


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
