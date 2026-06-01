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


# ── DART fundamental features (Korea-only model) ──────────────────────────────


def _kr_world():
    """6 KR tickers with distinct drifts (market='KOSDAQ')."""
    drifts = {"000001": 0.0015, "000002": 0.0010, "000003": 0.0005,
              "000004": -0.0002, "000005": -0.0007, "000006": -0.0012}
    start = date(2019, 1, 1)
    pm = {}
    for t, dft in drifts.items():
        closes = [100 * (1 + dft) ** i for i in range(420)]
        pm[(t, "KOSDAQ")] = _make_df(start, closes, market="KOSDAQ")
    return pm


def _dart_hist(ticker: str, growth: float) -> pd.DataFrame:
    """Two annual reports, available well before the 2019 price window starts."""
    from app.collectors.dart_fundamentals import HISTORY_COLS
    rows = [
        {
            "available_from": date(2017, 3, 31), "fiscal_year": 2016,
            "revenue": 1000.0, "op_income": 100.0, "net_income": 80.0,
            "equity": 500.0, "assets": 1000.0, "debt": 500.0,
            "prev_revenue": 1000.0 / (1 + growth), "prev_op_income": 100.0 / (1 + growth),
        },
        {
            "available_from": date(2018, 3, 31), "fiscal_year": 2017,
            "revenue": 1000.0 * (1 + growth), "op_income": 100.0 * (1 + growth),
            "net_income": 80.0 * (1 + growth), "equity": 520.0,
            "assets": 1050.0, "debt": 530.0,
            "prev_revenue": 1000.0, "prev_op_income": 100.0,
        },
    ]
    return pd.DataFrame(rows, columns=HISTORY_COLS)


def test_dart_features_attach_to_kr_dataset():
    pm = _kr_world()
    # higher-drift tickers also get higher fundamental growth (aligned signal)
    growths = [0.30, 0.20, 0.10, -0.05, -0.10, -0.15]
    hist = {t: _dart_hist(t, g) for (t, _), g in zip(pm.keys(), growths)}
    df = dataset.build_dataset(
        price_map=pm, index_map={}, years=1.0,
        include_dart=True, dart_history=hist,
    )
    assert not df.empty
    # both price and DART feature columns present
    assert set(dataset.FEATURE_COLS).issubset(df.columns)
    assert set(dataset.DART_FEATURE_COLS).issubset(df.columns)
    # revenue growth was encoded point-in-time and is non-null
    assert df["f_revenue_growth"].notna().all()


def test_dart_point_in_time_excludes_not_yet_public_fundamentals():
    pm = _kr_world()
    # fundamentals only become public in 2099 — after the whole price window →
    # they must NEVER enter as features (no leakage of not-yet-filed reports).
    # The dataset still builds (price-only); the DART columns are simply absent.
    future_hist = {}
    for (t, _) in pm:
        h = _dart_hist(t, 0.1)
        h["available_from"] = [date(2099, 1, 1), date(2099, 1, 1)]
        future_hist[t] = h
    df = dataset.build_dataset(
        price_map=pm, index_map={}, years=1.0,
        include_dart=True, dart_history=future_hist,
    )
    assert not df.empty  # price features keep the panel usable
    # not-yet-public fundamentals were dropped, never leaked as features
    assert not set(dataset.DART_FEATURE_COLS).intersection(df.columns)
    assert set(dataset.FEATURE_COLS).issubset(df.columns)


def test_dart_partial_coverage_imputes_not_drops():
    """Some KR tickers lack fundamentals → rows kept, gaps filled (not dropped)."""
    pm = _kr_world()
    keys = list(pm.keys())
    growths = [0.30, 0.20, 0.10, -0.05, -0.10]  # 5 of 6 have data
    from app.collectors.dart_fundamentals import HISTORY_COLS
    hist = {t: _dart_hist(t, g) for (t, _), g in zip(keys, growths)}
    # 6th ticker: no DART history at all
    hist[keys[5][0]] = pd.DataFrame(columns=HISTORY_COLS)
    df = dataset.build_dataset(
        price_map=pm, index_map={}, years=1.0,
        include_dart=True, dart_history=hist,
    )
    assert not df.empty
    # 5/6 = 83% coverage > 30% → columns survive and are fully imputed
    assert set(dataset.DART_FEATURE_COLS).issubset(df.columns)
    assert df["f_revenue_growth"].notna().all()
    # the no-data ticker still appears in the panel
    assert keys[5][0] in set(df["ticker"])


def test_kr_model_trains_with_dart_features():
    pm = _kr_world()
    growths = [0.30, 0.20, 0.10, -0.05, -0.10, -0.15]
    hist = {t: _dart_hist(t, g) for (t, _), g in zip(pm.keys(), growths)}
    df = dataset.build_dataset(
        price_map=pm, index_map={}, years=1.0,
        include_dart=True, dart_history=hist,
    )
    m = model.train_logistic(df)
    # model picked up all feature columns including DART
    assert set(dataset.DART_FEATURE_COLS).issubset(m.features)
    probs = m.predict_proba(df.head(5))
    assert probs.shape == (5,)
    assert np.all((probs >= 0) & (probs <= 1))
