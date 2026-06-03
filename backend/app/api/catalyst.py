"""Event-driven catalyst strategy — pre-registered picks + live scoring loop.

Endpoints:
  POST /catalyst/run        — generate catalyst picks for a market, store the
                              top-N as immutable predictions (박제), and score
                              any predictions whose horizon has elapsed (채점).
                              Runs in a background thread; poll until status=ok.
  GET  /catalyst/picks      — latest generated batch (from the last run).
  GET  /catalyst/history    — recently stored predictions (with outcomes).
  GET  /catalyst/scoreboard — aggregate live track record.

Honesty: every stored pick carries a PRE-REGISTERED thesis and an immutable
created_at, so the scoreboard is a genuine forward (out-of-sample) record — not
a re-run of history. The benchmark (index) return over the same window is
stored so "up" is always measured as EXCESS over the market, never absolute.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from app.db import repo

router = APIRouter()
logger = logging.getLogger(__name__)

_INDEX_TICKER = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "NASDAQ": "^IXIC"}

# Background run store (mirrors the predict pattern).
_store: dict[str, dict] = {}
_CACHE_TTL = 3600


def _is_running(key: str) -> bool:
    e = _store.get(key)
    return bool(e and e["status"] == "running")


def _latest_close(ticker: str, market: str) -> float | None:
    from app.collectors.prices import get_ohlcv
    try:
        df = get_ohlcv(ticker, market, period_days=400)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


def _disclosures_and_news(ticker: str, market: str) -> tuple[list[dict], list[dict]]:
    """Fresh disclosures (KR) + news titles, without the sentiment Claude call."""
    from app.collectors.news import _fetch_dart_disclosures, _fetch_yf_news
    disclosures: list[dict] = []
    news: list[dict] = []
    try:
        if market.upper() in ("KOSDAQ", "KOSPI"):
            disclosures = _fetch_dart_disclosures(ticker, limit=8)
        news = _fetch_yf_news(ticker, limit=6) if market.upper() == "NASDAQ" else []
    except Exception as e:
        logger.debug("catalyst inputs failed %s: %s", ticker, e)
    return disclosures, news


# ── scoring: evaluate predictions whose horizon has elapsed ──────────────────

def _score_due() -> int:
    """Score every due, unscored prediction. Returns number scored."""
    from app.collectors.prices import get_ohlcv
    now = datetime.now(timezone.utc)
    due = repo.get_due_unscored(now.isoformat(), limit=200)
    scored = 0
    # cache index frames per market for the run
    idx_cache: dict[str, object] = {}

    def _index_close_at(market: str, when_iso: str) -> float | None:
        import pandas as pd
        m = market.upper()
        if m not in idx_cache:
            try:
                idx_cache[m] = get_ohlcv(_INDEX_TICKER.get(m, "^IXIC"), m, period_days=500)
            except Exception:
                idx_cache[m] = None
        idf = idx_cache[m]
        if idf is None or idf.empty:
            return None
        d = pd.to_datetime(idf["date"], errors="coerce")
        sl = idf[d <= pd.to_datetime(when_iso)]
        return float(sl["close"].iloc[-1]) if not sl.empty else None

    for p in due:
        try:
            feats = json.loads(p.get("features") or "{}")
        except (TypeError, ValueError):
            feats = {}
        exit_px = _latest_close(p["ticker"], p["market"])
        entry_px = p.get("entry_price")
        if exit_px is None or not entry_px:
            continue
        stock_ret = exit_px / entry_px - 1.0

        # benchmark: index return over the same window
        bench_ret = None
        idx_entry = feats.get("index_entry")
        idx_now = _index_close_at(p["market"], datetime.now(timezone.utc).isoformat())
        if idx_entry and idx_now:
            bench_ret = idx_now / idx_entry - 1.0

        excess = (stock_ret - bench_ret) if bench_ret is not None else stock_ret
        hit = 1 if excess > 0 else 0
        repo.record_score(
            p["id"], datetime.now(timezone.utc).isoformat(),
            exit_px, stock_ret, bench_ret, excess, hit,
        )
        scored += 1
    return scored


# ── reflection: post-mortem scored picks → distilled lessons ─────────────────

def _reflect_scored(limit: int = 50) -> tuple[int, int]:
    """Post-mortem every scored-but-unreflected pick. Returns (n_reflected, n_lessons)."""
    from app.services.catalyst import catalyst_postmortem
    rows = repo.get_scored_unreflected(limit=limit)
    n_reflected = n_lessons = 0
    for p in rows:
        window = _window_disclosures(p)
        res = catalyst_postmortem(p, window)
        if not res.get("available"):
            continue  # no key / transient error → retry on a later run
        now = datetime.now(timezone.utc).isoformat()
        repo.record_postmortem(p["id"], res.get("postmortem", ""), now)
        lesson_rows = []
        for l in res.get("lessons", []):
            scope = l.get("scope", "global")
            lesson_rows.append({
                "scope": scope,
                "ticker": p["ticker"] if scope == "ticker" else None,
                "market": p["market"] if scope == "ticker" else None,
                "catalyst_type": l.get("catalyst_type"),
                "lesson": l["lesson"],
                "source_prediction_id": p["id"],
                "hit": p.get("hit"),
                "excess_return": p.get("excess_return"),
            })
        n_lessons += repo.insert_lessons(lesson_rows)
        n_reflected += 1
    return n_reflected, n_lessons


def _window_disclosures(pred: dict) -> list[dict]:
    """Disclosures published during a pick's holding period (KR only)."""
    if (pred.get("market") or "").upper() not in ("KOSPI", "KOSDAQ"):
        return []
    from app.collectors.news import _fetch_dart_disclosures
    try:
        return _fetch_dart_disclosures(
            pred["ticker"], limit=10,
            start_date=pred.get("created_at"), end_date=pred.get("scored_at"),
        )
    except Exception:
        return []


def _lesson_strings(ticker: str, market: str) -> list[str]:
    """Flatten ticker-scoped + global lessons into prompt-ready strings."""
    d = repo.get_lessons(ticker, market)
    rows = (d.get("ticker") or []) + (d.get("global") or [])
    return [r["lesson"] for r in rows if r.get("lesson")]


# ── generation: build & store catalyst picks ─────────────────────────────────

def _run_catalyst(key: str, market_filter: str, horizon_days: int, limit: int,
                  use_claude: bool):
    """Background worker — serialised against other heavy jobs to bound memory."""
    from app.services.heavy import heavy_slot
    try:
        with heavy_slot(drop_caches=True):
            _build_catalyst_picks(key, market_filter, horizon_days, limit, use_claude)
    except Exception as e:
        logger.warning("[catalyst] failed: %s", e, exc_info=True)
        _store[key] = {"status": "error", "payload": {"error": str(e)}, "ts": time.time()}


def _build_catalyst_picks(key: str, market_filter: str, horizon_days: int,
                          limit: int, use_claude: bool):
    from app.collectors.universe import get_universe
    from app.collectors.prices import get_ohlcv
    from app.collectors.company_name import get_company_name
    from app.services.catalyst import catalyst_score
    if True:
        # 1) score anything that's come due first
        n_scored = _score_due()

        # 2) DART history (KR only) for earnings surprise — shared reader, cheap
        tickers = get_universe(market_filter)
        dart_hist: dict = {}
        if (market_filter or "").upper() in ("KOSDAQ", "KOSPI", "KR"):
            from app.collectors.dart_fundamentals import get_kr_fundamental_history
            for it in tickers:
                dart_hist[it["ticker"]] = get_kr_fundamental_history(
                    it["ticker"], years=2)

        # 3) index entry levels per market (for benchmark at scoring time)
        import pandas as pd
        idx_entry: dict[str, float] = {}
        for m in {it["market"] for it in tickers}:
            try:
                idf = get_ohlcv(_INDEX_TICKER.get(m, "^IXIC"), m, period_days=400)
                if idf is not None and not idf.empty:
                    idx_entry[m] = float(idf["close"].iloc[-1])
            except Exception:
                pass

        # 4) score each ticker
        cands: list[dict] = []
        for it in tickers:
            t, m = it["ticker"], it["market"]
            entry = _latest_close(t, m)
            if entry is None:
                continue
            disclosures, news = _disclosures_and_news(t, m)
            cs = catalyst_score(t, m, dart_history=dart_hist.get(t),
                                disclosures=disclosures, news=news,
                                use_claude=use_claude)
            name = it.get("name") or get_company_name(t, m)
            cands.append({
                "ticker": t, "market": m, "name": name,
                "score": cs["score"], "thesis": cs["thesis"],
                "entry_price": entry,
                "surprise": cs["surprise"], "catalyst": cs["catalyst"],
                "index_entry": idx_entry.get(m),
            })

        cands.sort(key=lambda r: r["score"], reverse=True)
        picks = cands[:limit]

        # 5) persist the top-N as immutable predictions
        now = datetime.now(timezone.utc)
        due = now + timedelta(days=horizon_days)
        rows = []
        for rank, c in enumerate(picks, start=1):
            rows.append({
                "strategy": "catalyst", "ticker": c["ticker"], "market": c["market"],
                "name": c["name"], "created_at": now.isoformat(),
                "horizon_days": horizon_days, "due_at": due.isoformat(),
                "score": c["score"], "rank": rank, "thesis": c["thesis"],
                "entry_price": c["entry_price"],
                "features": json.dumps({
                    "index_entry": c.get("index_entry"),
                    "surprise": c["surprise"], "catalyst": c["catalyst"],
                }, ensure_ascii=False),
            })
        n_stored = repo.insert_predictions(rows)

        _store[key] = {
            "status": "ok",
            "payload": {
                "status": "ok",
                "market": market_filter or "ALL",
                "horizon_days": horizon_days,
                "n_scored_due": n_scored,
                "n_stored": n_stored,
                "picks": [{
                    "rank": i + 1, "ticker": c["ticker"], "market": c["market"],
                    "name": c["name"], "score": c["score"], "thesis": c["thesis"],
                    "catalyst_type": c["catalyst"].get("catalyst_type"),
                    "direction": c["catalyst"].get("direction"),
                } for i, c in enumerate(picks)],
                "as_of": now.isoformat(),
                "disclaimer": (
                    "촉매 점수는 공시·실적 기반 가설이며 투자 권유가 아닙니다. "
                    "실제 적중은 /catalyst/scoreboard 에서 누적 검증됩니다."
                ),
            },
            "ts": time.time(),
        }
        logger.info("[catalyst] done: %d picks, %d scored", len(picks), n_scored)


# ── reflection loop: score → reflect → predict-with-feedback (watchlist) ─────

def _run_catalyst_loop(key: str, horizon_days: int, use_claude: bool):
    from app.services.heavy import heavy_slot
    try:
        with heavy_slot(drop_caches=True):
            _build_loop(key, horizon_days, use_claude)
    except Exception as e:
        logger.warning("[catalyst-loop] failed: %s", e, exc_info=True)
        _store[key] = {"status": "error", "payload": {"error": str(e)}, "ts": time.time()}


def _build_loop(key: str, horizon_days: int, use_claude: bool):
    from app.collectors.prices import get_ohlcv
    from app.collectors.company_name import get_company_name
    from app.services.catalyst import catalyst_score

    # 1) score due picks, then 2) post-mortem freshly-scored ones into lessons
    n_scored = _score_due()
    n_reflected, n_lessons = _reflect_scored()

    watch = repo.get_catalyst_watchlist(active_only=True)
    if not watch:
        _store[key] = {
            "status": "ok",
            "payload": {
                "status": "ok", "watchlist_empty": True,
                "n_scored_due": n_scored, "n_reflected": n_reflected,
                "n_lessons": n_lessons, "picks": [],
                "message": "워치리스트가 비어 있습니다. 추적할 종목을 먼저 추가하세요.",
            },
            "ts": time.time(),
        }
        return

    # 3) DART history (KR) for earnings surprise
    dart_hist: dict = {}
    kr = [w for w in watch if (w["market"] or "").upper() in ("KOSPI", "KOSDAQ")]
    if kr:
        from app.collectors.dart_fundamentals import get_kr_fundamental_history
        for w in kr:
            dart_hist[w["ticker"]] = get_kr_fundamental_history(w["ticker"], years=2)

    # 4) index entry levels per market (benchmark at scoring time)
    idx_entry: dict[str, float] = {}
    for m in {w["market"] for w in watch}:
        try:
            idf = get_ohlcv(_INDEX_TICKER.get(m, "^IXIC"), m, period_days=400)
            if idf is not None and not idf.empty:
                idx_entry[m] = float(idf["close"].iloc[-1])
        except Exception:
            pass

    # 5) predict EVERY watchlist name, injecting its accumulated lessons
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=horizon_days)
    rows, picks = [], []
    for w in watch:
        t, m = w["ticker"], w["market"]
        entry = _latest_close(t, m)
        if entry is None:
            continue
        disclosures, news = _disclosures_and_news(t, m)
        lessons = _lesson_strings(t, m) if use_claude else []
        cs = catalyst_score(t, m, dart_history=dart_hist.get(t),
                            disclosures=disclosures, news=news,
                            use_claude=use_claude, lessons=lessons)
        name = w.get("name") or get_company_name(t, m)
        rows.append({
            "strategy": "catalyst", "ticker": t, "market": m, "name": name,
            "created_at": now.isoformat(), "horizon_days": horizon_days,
            "due_at": due.isoformat(), "score": cs["score"], "rank": None,
            "thesis": cs["thesis"], "entry_price": entry,
            "features": json.dumps({
                "index_entry": idx_entry.get(m),
                "surprise": cs["surprise"], "catalyst": cs["catalyst"],
                "lessons_used": lessons,
            }, ensure_ascii=False),
        })
        picks.append({
            "ticker": t, "market": m, "name": name, "score": cs["score"],
            "thesis": cs["thesis"], "catalyst_type": cs["catalyst"].get("catalyst_type"),
            "direction": cs["catalyst"].get("direction"),
            "lessons_used": len(lessons),
        })

    picks.sort(key=lambda r: r["score"], reverse=True)
    n_stored = repo.insert_predictions(rows)

    _store[key] = {
        "status": "ok",
        "payload": {
            "status": "ok", "horizon_days": horizon_days,
            "n_scored_due": n_scored, "n_reflected": n_reflected,
            "n_lessons": n_lessons, "n_stored": n_stored,
            "picks": [{"rank": i + 1, **p} for i, p in enumerate(picks)],
            "as_of": now.isoformat(),
            "disclaimer": (
                "촉매 점수는 공시·실적 기반 가설이며 투자 권유가 아닙니다. "
                "매 사이클 만기 픽을 채점하고 사후분석한 교훈을 다음 예측에 반영합니다."
            ),
        },
        "ts": time.time(),
    }
    logger.info("[catalyst-loop] %d picks, %d scored, %d reflected, %d lessons",
                n_stored, n_scored, n_reflected, n_lessons)


@router.get("/catalyst/loop/run")
def catalyst_loop_run(
    horizon_days: int = Query(21, ge=5, le=120),
    use_claude: bool = Query(True),
) -> dict:
    key = f"catalyst-loop:{horizon_days}"
    e = _store.get(key)
    if e and e["status"] == "ok" and (time.time() - e["ts"]) < _CACHE_TTL:
        return {**e["payload"], "cached": True}
    if _is_running(key):
        return {"status": "running", "message": "촉매 루프 실행 중…"}
    _store[key] = {"status": "running", "payload": {}, "ts": time.time()}
    threading.Thread(
        target=_run_catalyst_loop, args=(key, horizon_days, use_claude),
        daemon=True, name="catalyst-loop-bg",
    ).start()
    return {"status": "running", "message": "촉매 루프 시작됨 — 채점·사후분석·재예측. 자동 폴링."}


@router.get("/catalyst/watchlist")
def catalyst_watchlist_list() -> dict:
    return {"watchlist": repo.get_catalyst_watchlist(active_only=True)}


@router.post("/catalyst/watchlist/add")
def catalyst_watchlist_add(
    ticker: str = Query(...),
    market: str = Query(...),
    name: str | None = Query(None),
) -> dict:
    row = repo.add_catalyst_watchlist(ticker.strip(), market.strip().upper(), name)
    return {"status": "ok", "item": row}


@router.post("/catalyst/watchlist/remove")
def catalyst_watchlist_remove(id: int = Query(...)) -> dict:
    repo.remove_catalyst_watchlist(id)
    return {"status": "ok"}


@router.get("/catalyst/lessons")
def catalyst_lessons(limit: int = Query(50, ge=1, le=200)) -> dict:
    rows = repo.get_all_lessons(limit=limit)
    return {"lessons": rows, "count": len(rows)}


@router.get("/catalyst/run")
def catalyst_run(
    market: str = Query("KR"),
    horizon_days: int = Query(21, ge=5, le=120),
    limit: int = Query(10, ge=1, le=50),
    use_claude: bool = Query(True),
) -> dict:
    market_filter = market.upper() if market else "KR"
    key = f"catalyst:{market_filter}:{horizon_days}:{limit}"
    e = _store.get(key)
    if e and e["status"] == "ok" and (time.time() - e["ts"]) < _CACHE_TTL:
        return {**e["payload"], "cached": True}
    if _is_running(key):
        return {"status": "running", "message": "촉매 분석 중…"}
    _store[key] = {"status": "running", "payload": {}, "ts": time.time()}
    threading.Thread(
        target=_run_catalyst,
        args=(key, market_filter, horizon_days, limit, use_claude),
        daemon=True, name="catalyst-bg",
    ).start()
    return {"status": "running", "message": "촉매 분석 시작됨 — 1~2분 소요. 자동 폴링."}


@router.get("/catalyst/history")
def catalyst_history(strategy: str = Query("catalyst"), limit: int = Query(100, ge=1, le=500)) -> dict:
    rows = repo.get_recent_predictions(strategy=strategy or None, limit=limit)
    return {"predictions": rows, "count": len(rows)}


@router.get("/catalyst/scoreboard")
def catalyst_scoreboard(strategy: str = Query("catalyst")) -> dict:
    return repo.scoreboard(strategy=strategy or None)
