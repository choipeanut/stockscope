"""Phase-1 ML dataset builder (point-in-time).

Turns price history into a supervised-learning panel:
    features (momentum components, known at decision date)
    -> label  (did the stock out-perform the cross-section over the next window?)

Critical correctness rules (same as the backtest engine):
  - Features at row `as_of` use ONLY price data up to and including `as_of`.
  - The label uses returns measured strictly AFTER `as_of`.
  - The label is CROSS-SECTIONAL: "beat the median forward return on this date".
    This removes market-wide drift (you can't predict the market, only relative
    winners), which is the only honestly predictable target.

The output DataFrame has one row per (ticker, rebalance_date) and columns:
    date, ticker, market, <feature columns...>, fwd_return, label
where label = 1 if fwd_return > the cross-sectional median that date, else 0.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from app.backtest.engine import (
    _MIN_HISTORY_ROWS,
    _all_trading_dates,
    _forward_return,
    _load_index,
    _load_prices,
    _slice_up_to,
)
from app.collectors.universe import get_universe
from app.scoring.momentum import WEIGHTS as _MOM_WEIGHTS
from app.scoring.momentum import compute_momentum

logger = logging.getLogger(__name__)

# Feature columns = momentum sub-components (all price-derived, point-in-time safe)
FEATURE_COLS: list[str] = list(_MOM_WEIGHTS.keys())

# DART fundamental features (Korea-only model). Appended to FEATURE_COLS when a
# KR fundamental history is supplied. All point-in-time via `available_from`.
DART_FEATURE_COLS: list[str] = [
    "f_revenue_growth",   # YoY revenue growth %
    "f_profit_growth",    # YoY operating-income growth %
    "f_roe",              # net income / equity %
    "f_op_margin",        # operating income / revenue %
    "f_debt_ratio",       # debt / equity %
]


def _pct_growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _dart_features_at(history: pd.DataFrame | None, as_of) -> dict[str, float] | None:
    """Point-in-time DART fundamental vector at `as_of`, or None if unknowable.

    Uses the most recent annual report whose `available_from <= as_of` (so the
    numbers were already public). Returns None if no report was public yet — the
    KR model requires fundamentals, so such rows are dropped upstream.
    """
    if history is None or history.empty:
        return None
    as_of_dt = pd.to_datetime(as_of)
    avail = pd.to_datetime(history["available_from"], errors="coerce")
    usable = history[avail <= as_of_dt]
    if usable.empty:
        return None
    rec = usable.iloc[-1]  # history is sorted by available_from ascending

    revenue = rec.get("revenue")
    op_income = rec.get("op_income")
    net_income = rec.get("net_income")
    equity = rec.get("equity")

    rev_growth = _pct_growth(revenue, rec.get("prev_revenue"))
    profit_growth = _pct_growth(op_income, rec.get("prev_op_income"))
    roe = (net_income / equity * 100.0) if (net_income is not None and equity) else None
    op_margin = (op_income / revenue * 100.0) if (op_income is not None and revenue) else None
    debt_ratio = (rec.get("debt") / equity * 100.0) if (rec.get("debt") is not None and equity) else None

    feats = {
        "f_revenue_growth": rev_growth,
        "f_profit_growth": profit_growth,
        "f_roe": roe,
        "f_op_margin": op_margin,
        "f_debt_ratio": debt_ratio,
    }
    # require all present to keep the matrix clean (consistent with _features_at)
    if any(v is None for v in feats.values()):
        return None
    return {k: float(v) for k, v in feats.items()}


def _features_at(
    df_slice: pd.DataFrame, index_slice: pd.DataFrame | None
) -> dict[str, float] | None:
    """Point-in-time momentum component vector, or None if not computable."""
    if df_slice is None or len(df_slice) < _MIN_HISTORY_ROWS:
        return None
    try:
        res = compute_momentum(df_slice, index_slice)
    except Exception:
        return None
    comps = res.components or {}
    # require all features present (no partial rows — keeps the matrix clean)
    if not all(c in comps for c in FEATURE_COLS):
        return None
    return {c: float(comps[c]) for c in FEATURE_COLS}


def build_dataset(
    market: str | None = None,
    years: float = 5.0,
    rebalance_days: int = 21,
    holding_days: int = 21,
    price_map: dict | None = None,
    index_map: dict | None = None,
    include_dart: bool = False,
    dart_history: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Build the point-in-time supervised panel.

    Args:
        market: "KOSDAQ" | "NASDAQ" | None (both)
        years: history depth
        rebalance_days: trading-day gap between sample dates
        holding_days: forward-return horizon
        price_map/index_map: injectable for testing (skips network)
        include_dart: also attach DART fundamental features (KR model). Rows
            without public fundamentals at the decision date are dropped.
        dart_history: injectable {ticker: history_df}; fetched on demand if None.
    """
    lookback_days = int(years * 365) + 200

    if price_map is None:
        tickers = get_universe(market)
        price_map = _load_prices(tickers, lookback_days)
    if index_map is None:
        markets = {m for (_, m) in price_map}
        index_map = {m: _load_index(m, lookback_days) for m in markets}

    # Lazily fetch DART history for the tickers we actually have prices for.
    if include_dart and dart_history is None:
        from app.collectors.dart_fundamentals import get_kr_fundamental_history
        dart_history = {}
        for (t, m) in price_map:
            if m == "KOSDAQ":
                dart_history[t] = get_kr_fundamental_history(t, years=int(years) + 1)

    trading_dates = _all_trading_dates(price_map)
    if not trading_dates:
        empty_cols = ["date", "ticker", "market", *FEATURE_COLS, "fwd_return", "label"]
        return pd.DataFrame(columns=empty_cols)

    start_idx = _MIN_HISTORY_ROWS
    end_idx = len(trading_dates) - holding_days - 1
    decision_idxs = range(start_idx, max(start_idx, end_idx), rebalance_days)

    rows: list[dict] = []
    for di in decision_idxs:
        as_of: date = trading_dates[di]
        day_rows: list[dict] = []
        for (t, m), df in price_map.items():
            sl = _slice_up_to(df, as_of)
            idx = index_map.get(m)
            idx_sl = _slice_up_to(idx, as_of) if idx is not None else None
            feats = _features_at(sl, idx_sl)
            if feats is None:
                continue
            row = {"date": as_of, "ticker": t, "market": m, **feats}
            if include_dart:
                # DART enriches but never blocks: missing fundamentals stay NaN
                # and are imputed (or the column is dropped) after assembly. A
                # None here means "not yet public at as_of" → correctly absent.
                dart_feats = _dart_features_at((dart_history or {}).get(t), as_of)
                for col in DART_FEATURE_COLS:
                    row[col] = float((dart_feats or {}).get(col, float("nan")))
            fr = _forward_return(df, as_of, holding_days)
            if np.isnan(fr):
                continue
            row["fwd_return"] = fr
            day_rows.append(row)

        if len(day_rows) < 3:
            continue  # need a cross-section to define "beat the median"

        med = float(np.median([r["fwd_return"] for r in day_rows]))
        for r in day_rows:
            r["label"] = 1 if r["fwd_return"] > med else 0
        rows.extend(day_rows)

    feature_cols = [*FEATURE_COLS, *DART_FEATURE_COLS] if include_dart else list(FEATURE_COLS)
    cols = ["date", "ticker", "market", *feature_cols, "fwd_return", "label"]
    result = pd.DataFrame(rows, columns=cols)

    if include_dart and not result.empty:
        result = _impute_or_drop_dart(result)
    return result


def _impute_or_drop_dart(df: pd.DataFrame, min_coverage: float = 0.30) -> pd.DataFrame:
    """Make DART columns usable without ever emptying the dataset.

    For each DART feature column:
      - if fewer than `min_coverage` of rows have a value, the signal is too
        sparse to trust → drop the column (model falls back to price features);
      - otherwise fill gaps with the SAME-DATE cross-sectional median (leak-free,
        uses only that day's peers), with a global-median backstop for any date
        that had no values at all.
    """
    for col in DART_FEATURE_COLS:
        if col not in df.columns:
            continue
        if df[col].notna().mean() < min_coverage:
            df = df.drop(columns=[col])
            continue
        df[col] = df.groupby("date")[col].transform(lambda s: s.fillna(s.median()))
        df[col] = df[col].fillna(df[col].median())
    return df
