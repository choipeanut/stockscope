"""GET /backtest, /predict/eval, /predict — prediction & backtest endpoints.

All heavy endpoints (predict, predict/eval) run in a background thread and
return immediately with status="running". The client polls until status="ok".
This mirrors the /screen pattern and avoids gateway timeouts on small servers.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict

from fastapi import APIRouter, Query

from app.backtest.engine import run_backtest

router = APIRouter()
logger = logging.getLogger(__name__)

_CACHE_TTL = 3600  # 1 hour

# ---------------------------------------------------------------------------
# Shared in-memory store: key → {status, payload, started_at}
# ---------------------------------------------------------------------------
_store: dict[str, dict] = {}
_locks: dict[str, threading.Lock] = {}


def _get_lock(key: str) -> threading.Lock:
    if key not in _locks:
        _locks[key] = threading.Lock()
    return _locks[key]


def _is_fresh(key: str) -> bool:
    entry = _store.get(key)
    if not entry or entry["status"] != "ok":
        return False
    return (time.time() - entry["ts"]) < _CACHE_TTL


def _is_running(key: str) -> bool:
    entry = _store.get(key)
    return bool(entry and entry["status"] == "running")


def _running_response(msg: str) -> dict:
    return {"status": "running", "message": msg}


# ---------------------------------------------------------------------------
# Shared dataset cache (avoid rebuilding for /predict after /predict/eval)
# One lock ensures concurrent threads don't both build at the same time —
# a double build would double peak memory and OOM on a 512 MB box.
# ---------------------------------------------------------------------------
_dataset_cache: dict[str, tuple[float, object]] = {}
_dataset_lock = threading.Lock()


def _get_dataset(market_filter, years, rebalance_days, holding_days):
    from app.backtest.dataset import build_dataset
    # Korea-only request → enrich with point-in-time DART fundamentals.
    include_dart = market_filter == "KOSDAQ"
    key = f"ds:{market_filter}:{years}:{rebalance_days}:{holding_days}:dart={include_dart}"
    # Hold the lock for the entire build: concurrent builds double peak memory
    # and OOM a 512 MB box. Background threads don't block HTTP requests, so
    # holding this lock for 20-30 s is fine.
    with _dataset_lock:
        cached = _dataset_cache.get(key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
        df = build_dataset(
            market=market_filter, years=years,
            rebalance_days=rebalance_days, holding_days=holding_days,
            include_dart=include_dart,
        )
        # Keep only the most-recently built panel in memory.
        _dataset_cache.clear()
        _dataset_cache[key] = (time.time(), df)
        return df


# ---------------------------------------------------------------------------
# /backtest  (synchronous — smaller computation)
# ---------------------------------------------------------------------------
@router.get("/backtest")
def backtest(
    market: str = Query(""),
    factor: str = Query("momentum"),
    years: float = Query(3.0, ge=0.5, le=10.0),
    rebalance_days: int = Query(21, ge=5, le=120),
    holding_days: int = Query(21, ge=5, le=120),
    n_quantiles: int = Query(5, ge=2, le=10),
) -> dict:
    market_filter = market.upper() if market else None
    key = f"bt:{market_filter}:{factor}:{years}:{rebalance_days}:{holding_days}:{n_quantiles}"
    if _is_fresh(key):
        return {**_store[key]["payload"], "cached": True}

    result = run_backtest(
        market=market_filter, factor=factor, years=years,
        rebalance_days=rebalance_days, holding_days=holding_days,
        n_quantiles=n_quantiles,
    )
    payload = asdict(result)
    _store[key] = {"status": "ok", "payload": payload, "ts": time.time()}
    return {**payload, "cached": False}


# ---------------------------------------------------------------------------
# /predict/eval  — background build + walk-forward eval
# ---------------------------------------------------------------------------
def _run_predict_eval(key, market_filter, years, rebalance_days, holding_days, n_splits):
    from dataclasses import asdict as _asdict
    from app.backtest.model import walk_forward_eval
    try:
        df = _get_dataset(market_filter, years, rebalance_days, holding_days)
        report = walk_forward_eval(df, n_splits=n_splits)
        payload = {
            "market": market_filter or "ALL",
            "n_samples": int(len(df)),
            "report": _asdict(report),
        }
        _store[key] = {"status": "ok", "payload": payload, "ts": time.time()}
        logger.info("[predict/eval] done: %s", key)
    except Exception as e:
        logger.warning("[predict/eval] failed: %s", e, exc_info=True)
        _store[key] = {"status": "error", "payload": {"error": str(e)}, "ts": time.time()}


@router.get("/predict/eval")
def predict_eval(
    market: str = Query(""),
    years: float = Query(3.0, ge=1.0, le=10.0),
    rebalance_days: int = Query(21, ge=5, le=120),
    holding_days: int = Query(21, ge=5, le=120),
    n_splits: int = Query(4, ge=1, le=10),
) -> dict:
    market_filter = market.upper() if market else None
    key = f"eval:{market_filter}:{years}:{rebalance_days}:{holding_days}:{n_splits}"

    if _is_fresh(key):
        return {**_store[key]["payload"], "cached": True}
    if _is_running(key):
        return _running_response("모델 검증 중…")

    _store[key] = {"status": "running", "payload": {}, "ts": time.time()}
    threading.Thread(
        target=_run_predict_eval,
        args=(key, market_filter, years, rebalance_days, holding_days, n_splits),
        daemon=True, name="predict-eval-bg",
    ).start()
    return _running_response("모델 검증 시작됨 — 1~3분 소요. 자동으로 폴링합니다.")


# ---------------------------------------------------------------------------
# /predict  — background train + rank current universe
# ---------------------------------------------------------------------------
def _run_predict(key, market_filter, years, holding_days, limit):
    from datetime import datetime, timezone
    import pandas as pd
    from app.backtest.dataset import _dart_features_at, _features_at
    from app.backtest.engine import _load_index, _load_prices, _slice_up_to
    from app.backtest.model import train_logistic
    from app.collectors.company_name import get_company_name
    from app.collectors.universe import get_universe
    try:
        df = _get_dataset(market_filter, years, 21, holding_days)
        if df.empty or df["label"].nunique() < 2:
            logger.warning(
                "[predict] insufficient data: market=%s years=%s holding=%s rows=%d labels=%s",
                market_filter, years, holding_days,
                len(df), df["label"].unique().tolist() if not df.empty else [],
            )
            _store[key] = {
                "status": "ok",
                "payload": {"status": "insufficient_data", "predictions": [], "as_of": None},
                "ts": time.time(),
            }
            return

        model = train_logistic(df)
        include_dart = market_filter == "KOSDAQ"
        lookback_days = int(years * 365) + 200
        tickers = get_universe(market_filter)
        price_map = _load_prices(tickers, lookback_days)
        markets = {m for (_, m) in price_map}
        index_map = {m: _load_index(m, lookback_days) for m in markets}

        dart_hist = {}
        if include_dart:
            from app.collectors.dart_fundamentals import get_kr_fundamental_history
            for (t, m) in price_map:
                if m == "KOSDAQ":
                    dart_hist[t] = get_kr_fundamental_history(t, years=int(years) + 1)

        today = datetime.now(timezone.utc).date()
        # Pass 1: collect candidates. DART features may be missing for some
        # tickers — kept as NaN and imputed cross-sectionally below (matching the
        # training-time treatment), so a missing fundamental never drops a name.
        dart_cols = [c for c in model.features if c.startswith("f_")]
        candidates: list[dict] = []
        for (t, m), pdf in price_map.items():
            # date columns are already clean datetime64 from _load_prices/_load_index
            idx = index_map.get(m)
            idx_sl = _slice_up_to(idx, idx["date"].max()) if idx is not None else None
            feats = _features_at(_slice_up_to(pdf, pdf["date"].max()), idx_sl)
            if feats is None:
                continue
            if dart_cols:
                dart_feats = _dart_features_at(dart_hist.get(t), today) or {}
                for c in dart_cols:
                    v = dart_feats.get(c)
                    feats[c] = float(v) if v is not None else float("nan")
            name = next((i.get("name", "") for i in tickers if i["ticker"] == t), "")
            name = name or get_company_name(t, m)
            candidates.append({"ticker": t, "market": m, "name": name, "feats": feats})

        if not candidates:
            _store[key] = {
                "status": "ok",
                "payload": {"status": "insufficient_data", "predictions": [], "as_of": None},
                "ts": time.time(),
            }
            return

        feat_df = pd.DataFrame([c["feats"] for c in candidates])
        # impute missing DART columns with the current cross-sectional median
        for c in dart_cols:
            if c in feat_df.columns:
                feat_df[c] = feat_df[c].fillna(feat_df[c].median())
                feat_df[c] = feat_df[c].fillna(0.0)  # backstop if all NaN
        probs = model.predict_proba(feat_df)

        preds: list[dict] = []
        for cand, prob, (_, frow) in zip(candidates, probs, feat_df.iterrows()):
            preds.append({
                "ticker": cand["ticker"], "market": cand["market"], "name": cand["name"],
                "probability": round(float(prob), 4),
                "features": {k: round(float(v), 2) for k, v in frow.items()},
            })

        preds.sort(key=lambda r: r["probability"], reverse=True)
        payload = {
            "status": "ok",
            "market": market_filter or "ALL",
            "horizon_days": holding_days,
            "n_train_samples": int(len(df)),
            "predictions": preds[:limit],
            "as_of": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "확률은 모델 추정치이며 투자 권유가 아닙니다. 실제 예측력은 /predict/eval 참조."
            ),
        }
        _store[key] = {"status": "ok", "payload": payload, "ts": time.time()}
        logger.info("[predict] done: %d preds", len(preds))
    except Exception as e:
        logger.warning("[predict] failed: %s", e, exc_info=True)
        _store[key] = {"status": "error", "payload": {"error": str(e)}, "ts": time.time()}


# ---------------------------------------------------------------------------
# /predict/dart-check  — diagnostic: is DART actually parsing for a ticker?
# ---------------------------------------------------------------------------
@router.get("/predict/dart-check")
def dart_check(ticker: str = Query("005930"), year: int = Query(0)) -> dict:
    """Step-by-step DART diagnostic so we can see exactly where parsing fails:
    corp_code lookup → finstate_all call → available account columns/values."""
    import os
    from datetime import datetime, timezone
    from app.collectors.dart_fundamentals import get_kr_fundamental_history

    out: dict = {"ticker": ticker, "dart_api_key_present": bool(os.environ.get("DART_API_KEY"))}
    if not out["dart_api_key_present"]:
        return out

    def _safe_records(df, cols, n):
        """JSON-safe: every cell stringified, NaN → None (avoids numpy 500s)."""
        recs = []
        for _, r in df[cols].head(n).iterrows():
            rec = {}
            for c in cols:
                v = r[c]
                rec[c] = None if pd_isna(v) else str(v)
            recs.append(rec)
        return recs

    probe_year = year or (datetime.now(timezone.utc).year - 1)
    try:
        import pandas as pd
        pd_isna = pd.isna
        from app.collectors.dart_fundamentals import make_reader
        dr = make_reader(os.environ["DART_API_KEY"])
        codes = dr.corp_codes
        out["corp_codes_columns"] = [str(c) for c in codes.columns]
        match = codes[codes["stock_code"] == ticker]
        out["corp_code_found"] = bool(match is not None and not match.empty)
        if out["corp_code_found"]:
            corp_code = match.iloc[0]["corp_code"]
            out["corp_code"] = str(corp_code)
            try:
                fs = dr.finstate_all(corp_code, probe_year, reprt_code="11011")
                out["probe_year"] = probe_year
                if fs is None or fs.empty:
                    out["finstate_rows"] = 0
                else:
                    out["finstate_rows"] = int(len(fs))
                    out["finstate_columns"] = [str(c) for c in fs.columns]
                    cols = [c for c in ["sj_div", "fs_div", "account_id", "account_nm",
                                        "thstrm_amount", "frmtrm_amount"] if c in fs.columns]
                    out["sample_rows"] = _safe_records(fs, cols, 25)
            except Exception as e:
                out["finstate_error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"

    # also run the real parser
    try:
        hist = get_kr_fundamental_history(ticker, years=6)
        out["rows_parsed"] = int(len(hist))
        out["history"] = (
            _safe_records(hist, list(hist.columns), len(hist)) if not hist.empty else []
        )
    except Exception as e:
        out["parser_error"] = f"{type(e).__name__}: {e}"
    return out


@router.get("/predict")
def predict(
    market: str = Query(""),
    years: float = Query(3.0, ge=1.0, le=10.0),
    holding_days: int = Query(21, ge=5, le=120),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    market_filter = market.upper() if market else None
    key = f"pred:{market_filter}:{years}:{holding_days}:{limit}"

    if _is_fresh(key):
        return {**_store[key]["payload"], "cached": True}
    if _is_running(key):
        return _running_response("종목 랭킹 생성 중…")

    _store[key] = {"status": "running", "payload": {}, "ts": time.time()}
    threading.Thread(
        target=_run_predict,
        args=(key, market_filter, years, holding_days, limit),
        daemon=True, name="predict-bg",
    ).start()
    return _running_response("예측 시작됨 — 1~3분 소요. 자동으로 폴링합니다.")
