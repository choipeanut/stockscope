"""Phase-2 prediction model — dependency-light logistic regression (numpy only).

Predicts P(stock beats the cross-sectional median forward return) from the
point-in-time momentum features. Kept numpy-only so it deploys on Render with
no extra dependency; the interface is small enough to swap for sklearn
GradientBoosting or LightGBM later without touching callers.

Honesty guarantees:
  - WALK-FORWARD evaluation: train on dates strictly before a cutoff, test on
    dates after it. Never trains on the future.
  - Out-of-sample metrics only: AUC, accuracy, and rank-IC of the predicted
    probability vs the realized forward return.
  - Reports a BASELINE (predict 0.5 for everyone) so any "skill" is visible as
    improvement over chance.

Realistic expectation: out-of-sample AUC around 0.52-0.55 is already a real
edge. Anything near 0.7+ on this data almost certainly means a leakage bug.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtest.dataset import FEATURE_COLS

logger = logging.getLogger(__name__)

# Columns that are never features (metadata + target).
_META_COLS = {"date", "ticker", "market", "fwd_return", "label"}


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Feature columns present in `df` (everything that isn't metadata/target).

    Lets a Korea-only dataset with extra DART columns train without any caller
    changes; falls back to the canonical price FEATURE_COLS if df is empty.
    """
    cols = [c for c in df.columns if c not in _META_COLS]
    return cols or list(FEATURE_COLS)


@dataclass
class LogisticModel:
    weights: np.ndarray            # shape (n_features,)
    bias: float
    mean: np.ndarray               # feature standardization
    std: np.ndarray
    features: list[str] = field(default_factory=lambda: list(FEATURE_COLS))

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        Xn = _as_matrix(X, self.features)
        Xs = (Xn - self.mean) / self.std
        z = Xs @ self.weights + self.bias
        return 1.0 / (1.0 + np.exp(-z))


def _as_matrix(X: pd.DataFrame | np.ndarray, features: list[str]) -> np.ndarray:
    if isinstance(X, pd.DataFrame):
        return X[features].to_numpy(dtype=float)
    return np.asarray(X, dtype=float)


def train_logistic(
    df: pd.DataFrame,
    l2: float = 1.0,
    lr: float = 0.1,
    epochs: int = 500,
) -> LogisticModel:
    """Train standardized logistic regression by full-batch gradient descent."""
    features = feature_columns(df)
    X = df[features].to_numpy(dtype=float)
    y = df["label"].to_numpy(dtype=float)

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    Xs = (X - mean) / std

    n, d = Xs.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        z = Xs @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        grad_w = Xs.T @ (p - y) / n + l2 * w / n
        grad_b = float(np.mean(p - y))
        w -= lr * grad_w
        b -= lr * grad_b

    return LogisticModel(weights=w, bias=b, mean=mean, std=std, features=features)


def _rank_ic(prob: np.ndarray, fwd: np.ndarray) -> float | None:
    if len(prob) < 3:
        return None
    pr = pd.Series(prob).rank().to_numpy()
    fr = pd.Series(fwd).rank().to_numpy()
    if np.std(pr) == 0 or np.std(fr) == 0:
        return None
    return float(np.corrcoef(pr, fr)[0, 1])


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """ROC-AUC via the Mann-Whitney U statistic (no sklearn)."""
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = pd.Series(p).rank().to_numpy()  # average ranks handle ties
    sum_pos = ranks[y == 1].sum()
    auc = (sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


@dataclass
class WalkForwardReport:
    n_train: int
    n_test: int
    auc: float | None
    accuracy: float | None
    baseline_accuracy: float | None   # always predicting the majority class
    rank_ic: float | None
    n_splits: int
    feature_weights: dict[str, float] = field(default_factory=dict)


def walk_forward_eval(
    df: pd.DataFrame,
    n_splits: int = 4,
    min_train_frac: float = 0.5,
    embargo_days: int = 0,
) -> WalkForwardReport:
    """Expanding-window walk-forward evaluation by date.

    Splits the unique dates into an initial training block (min_train_frac) plus
    n_splits sequential test blocks; trains on everything before each block and
    tests on it, then pools out-of-sample predictions for the metrics.

    embargo_days: when decision dates are sampled more densely than the forward
    (holding) window — e.g. rebalance 10d but holding 21d — a training sample
    just before the cutoff has a forward-return window that overlaps into the
    test block, leaking test-period returns into its label. Purge those by
    dropping training rows within `embargo_days` CALENDAR days before each
    cutoff. 0 = no purge (safe only when rebalance >= holding, i.e. windows
    never overlap).
    """
    if df.empty:
        return WalkForwardReport(0, 0, None, None, None, None, 0)

    dates = np.array(sorted(df["date"].unique()))
    n_dates = len(dates)
    if n_dates < n_splits + 2:
        # too few dates for walk-forward — fall back to a single split
        n_splits = 1

    split_start = int(n_dates * min_train_frac)
    test_date_blocks = np.array_split(dates[split_start:], max(1, n_splits))

    # Precompute a datetime view once for embargo arithmetic (no-op when off).
    df_dt = pd.to_datetime(df["date"]) if embargo_days > 0 else None

    oos_y: list[np.ndarray] = []
    oos_p: list[np.ndarray] = []
    oos_fwd: list[np.ndarray] = []
    total_train = 0

    for block in test_date_blocks:
        if len(block) == 0:
            continue
        cutoff = block[0]
        if embargo_days > 0:
            embargo_cutoff = pd.Timestamp(cutoff) - pd.Timedelta(days=embargo_days)
            train = df[df_dt < embargo_cutoff]
        else:
            train = df[df["date"] < cutoff]
        test = df[df["date"].isin(block)]
        if len(train) < 20 or test.empty:
            continue
        # need both classes in training
        if train["label"].nunique() < 2:
            continue
        model = train_logistic(train)
        p = model.predict_proba(test)
        oos_y.append(test["label"].to_numpy(dtype=float))
        oos_p.append(p)
        oos_fwd.append(test["fwd_return"].to_numpy(dtype=float))
        total_train = len(train)

    if not oos_y:
        return WalkForwardReport(0, 0, None, None, None, None, 0)

    y = np.concatenate(oos_y)
    p = np.concatenate(oos_p)
    fwd = np.concatenate(oos_fwd)

    pred = (p >= 0.5).astype(float)
    acc = float(np.mean(pred == y))
    majority = float(max(np.mean(y), 1 - np.mean(y)))  # baseline: always majority class

    # final model on all data for reporting feature weights
    final = train_logistic(df) if df["label"].nunique() >= 2 else None
    fw = (
        {f: round(float(w), 4) for f, w in zip(final.features, final.weights)}
        if final is not None else {}
    )

    return WalkForwardReport(
        n_train=total_train,
        n_test=len(y),
        auc=_round(_auc(y, p)),
        accuracy=round(acc, 4),
        baseline_accuracy=round(majority, 4),
        rank_ic=_round(_rank_ic(p, fwd)),
        n_splits=len([b for b in test_date_blocks if len(b)]),
        feature_weights=fw,
    )


def _round(x: float | None, nd: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)
