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
) -> pd.DataFrame:
    """Build the point-in-time supervised panel.

    Args:
        market: "KOSDAQ" | "NASDAQ" | None (both)
        years: history depth
        rebalance_days: trading-day gap between sample dates
        holding_days: forward-return horizon
        price_map/index_map: injectable for testing (skips network)
    """
    lookback_days = int(years * 365) + 200

    if price_map is None:
        tickers = get_universe(market)
        price_map = _load_prices(tickers, lookback_days)
    if index_map is None:
        markets = {m for (_, m) in price_map}
        index_map = {m: _load_index(m, lookback_days) for m in markets}

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
            fr = _forward_return(df, as_of, holding_days)
            if np.isnan(fr):
                continue
            day_rows.append({
                "date": as_of, "ticker": t, "market": m,
                **feats, "fwd_return": fr,
            })

        if len(day_rows) < 3:
            continue  # need a cross-section to define "beat the median"

        med = float(np.median([r["fwd_return"] for r in day_rows]))
        for r in day_rows:
            r["label"] = 1 if r["fwd_return"] > med else 0
        rows.extend(day_rows)

    cols = ["date", "ticker", "market", *FEATURE_COLS, "fwd_return", "label"]
    return pd.DataFrame(rows, columns=cols)
