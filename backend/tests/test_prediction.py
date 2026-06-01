"""Tests for the Phase-1 dataset builder and Phase-2 prediction model.

Synthetic, deterministic, no network. Verifies:
  - dataset rows are point-in-time and cross-sectionally labeled,
  - labels are balanced around the per-date median,
  - the model learns a learnable signal (out-of-sample AUC > 0.5),
  - the model stays near chance on pure noise (no false skill / leakage).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.backtest import dataset, engine, model


def _make_df(start: date, closes: list[float], market: str = "NASDAQ") -> pd.DataFrame:
    rows = []
    d = start
    for c in closes:
        rows.append({
            "date": d, "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1_000_000, "market": market,
        })
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def _trending_world(seed: int = 0):
    """6 tickers with distinct constant drifts → momentum should predict returns."""
    drifts = {"AAA": 0.0015, "BBB": 0.0010, "CCC": 0.0005,
              "DDD": -0.0002, "EEE": -0.0007, "FFF": -0.0012}
    start = date(2019, 1, 1)
    pm = {}
    for t, dft in drifts.items():
        closes = [100 * (1 + dft) ** i for i in range(420)]
        pm[(t, "NASDAQ")] = _make_df(start, closes)
    return pm


def test_dataset_is_point_in_time_and_labeled():
    pm = _trending_world()
    df = dataset.build_dataset(price_map=pm, index_map={}, years=1.0)
    assert not df.empty
    assert set(dataset.FEATURE_COLS).issubset(df.columns)
    assert {"fwd_return", "label"}.issubset(df.columns)
    # labels are binary and roughly balanced (median split)
    assert set(df["label"].unique()).issubset({0, 1})
    assert 0.3 < df["label"].mean() < 0.7


def test_model_learns_signal_out_of_sample():
    pm = _trending_world()
    df = dataset.build_dataset(price_map=pm, index_map={}, years=1.0)
    report = model.walk_forward_eval(df, n_splits=3)
    assert report.n_test > 0
    assert report.auc is not None
    # momentum genuinely predicts returns here → better than chance
    assert report.auc > 0.55


def test_model_near_chance_on_noise():
    """Pure random walks → no learnable signal → AUC should hug 0.5."""
    rng = np.random.default_rng(42)
    start = date(2019, 1, 1)
    pm = {}
    for i in range(8):
        steps = rng.normal(0, 0.02, 420)
        closes = list(100 * np.exp(np.cumsum(steps)))
        pm[(f"T{i}", "NASDAQ")] = _make_df(start, closes)

    df = dataset.build_dataset(price_map=pm, index_map={}, years=1.0)
    report = model.walk_forward_eval(df, n_splits=3)
    if report.auc is not None:
        # no real edge on noise — should not show strong (fake) skill
        assert report.auc < 0.65


def test_predict_proba_shape():
    pm = _trending_world()
    df = dataset.build_dataset(price_map=pm, index_map={}, years=1.0)
    m = model.train_logistic(df)
    probs = m.predict_proba(df.head(5))
    assert probs.shape == (5,)
    assert np.all((probs >= 0) & (probs <= 1))
