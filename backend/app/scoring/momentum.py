"""Momentum sub-score (weight 0.15) — fully price-computable.

Components per ANALYSIS_SPEC §Momentum:
  추세 정렬   0.30  close>MA20>MA60>MA120
  RSI(14)     0.15  45-65 healthy; >75 overbought; <30 oversold mild bonus
  MACD        0.15  signal-line cross state + histogram sign
  거래량      0.15  breakout: vol > 1.5× MA20vol
  상대강도    0.15  stock 60d return − index 60d return
  신고가 근접 0.10  distance to 52-week high
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

WEIGHTS = {
    "trend_alignment": 0.30,
    "rsi": 0.15,
    "macd": 0.15,
    "volume": 0.15,
    "relative_strength": 0.15,
    "high52w": 0.10,
}


@dataclass
class MomentumResult:
    score: float
    components: dict[str, float]
    unavailable: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _safe_series(df: pd.DataFrame, col: str) -> pd.Series | None:
    if col not in df.columns or df[col].isna().all():
        return None
    return df[col].astype(float)


# ── helpers ─────────────────────────────────────────────────────────────────


def _trend_alignment(close: pd.Series) -> tuple[float, dict]:
    """Score 0-100 based on MA20/60/120 alignment."""
    if len(close) < 120:
        return float("nan"), {}
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()
    c = close.iloc[-1]
    m20 = ma20.iloc[-1]
    m60 = ma60.iloc[-1]
    m120 = ma120.iloc[-1]
    # perfect bull: c>m20>m60>m120 → 100; perfect bear: c<m20<m60<m120 → 0
    conditions = [c > m20, m20 > m60, m60 > m120]
    bull_count = sum(conditions)
    score = (bull_count / 3) * 100.0
    det = {"ma20": m20, "ma60": m60, "ma120": m120, "close": c, "bull_conditions": bull_count}
    return score, det


def _rsi(close: pd.Series, period: int = 14) -> tuple[float, float]:
    """Return (score 0-100, raw RSI)."""
    if len(close) < period + 1:
        return float("nan"), float("nan")
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_val = rsi_series.iloc[-1]
    if np.isnan(rsi_val):
        return float("nan"), float("nan")
    # Healthy zone 45–65 → 100; overbought >75 penalty; oversold <30 mild bonus
    if 45 <= rsi_val <= 65:
        score = 100.0
    elif rsi_val > 75:
        score = max(0.0, 100.0 - (rsi_val - 75) * 4)  # −4 per point above 75
    elif rsi_val < 30:
        score = 60.0  # mild oversold bonus (recovery potential)
    elif rsi_val < 45:
        score = (rsi_val - 30) / 15 * 70  # linear 0→70 from 30→45
    else:  # 65 < rsi <= 75
        score = 100.0 - (rsi_val - 65) * 3  # slight reduction
    return float(score), float(rsi_val)


def _macd(close: pd.Series) -> tuple[float, dict]:
    """Return (score 0-100, details) based on MACD cross state + histogram sign."""
    if len(close) < 35:
        return float("nan"), {}
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal

    macd_now = macd_line.iloc[-1]
    signal_now = signal.iloc[-1]
    hist_now = hist.iloc[-1]
    hist_prev = hist.iloc[-2] if len(hist) >= 2 else 0.0

    # Bullish: MACD > signal and histogram rising → 100
    # Bearish: MACD < signal and histogram falling → 0
    # Mixed → 50
    bull = macd_now > signal_now
    hist_rising = hist_now > hist_prev
    if bull and hist_rising:
        score = 100.0
    elif bull and not hist_rising:
        score = 65.0
    elif not bull and not hist_rising:
        score = 0.0
    else:
        score = 35.0
    return score, {"macd": macd_now, "signal": signal_now, "histogram": hist_now}


def _volume_surge(df: pd.DataFrame) -> tuple[float, dict]:
    """Score based on volume breakout (vol > 1.5× MA20 vol)."""
    close = _safe_series(df, "close")
    volume = _safe_series(df, "volume")
    if close is None or volume is None or len(volume) < 20:
        return float("nan"), {}
    vol_ma20 = volume.rolling(20).mean()
    vol_now = volume.iloc[-1]
    vol_avg = vol_ma20.iloc[-1]
    ratio = vol_now / vol_avg if vol_avg > 0 else 1.0
    if ratio >= 1.5:
        score = 100.0
    elif ratio >= 1.2:
        score = 70.0
    elif ratio >= 0.8:
        score = 50.0
    else:
        score = 20.0
    return score, {"volume_ratio": ratio, "volume_ma20": vol_avg}


def _relative_strength(
    close: pd.Series, index_close: pd.Series | None, period: int = 60
) -> tuple[float, dict]:
    """Stock 60d return minus index 60d return → percentile-like 0–100."""
    if len(close) < period + 1:
        return float("nan"), {}
    p0, p1 = -(period + 1), -1
    stock_ret = (close.iloc[p1] - close.iloc[p0]) / close.iloc[p0]
    if index_close is not None and len(index_close) >= period + 1:
        idx_ret = (index_close.iloc[p1] - index_close.iloc[p0]) / index_close.iloc[p0]
    else:
        idx_ret = 0.0
    rel = stock_ret - idx_ret
    # Map rel [-0.30, +0.30] → [0, 100] clamped
    score = float(np.clip((rel + 0.30) / 0.60 * 100, 0, 100))
    return score, {"stock_60d": stock_ret, "index_60d": idx_ret, "relative": rel}


def _high52w_proximity(close: pd.Series) -> tuple[float, dict]:
    """Distance to 52-week high → score (closer = higher)."""
    if len(close) < 20:
        return float("nan"), {}
    window = min(252, len(close))
    high52 = close.iloc[-window:].max()
    c = close.iloc[-1]
    dist = (high52 - c) / high52 if high52 > 0 else 0.0
    # dist=0 → 100; dist=0.30 → 0; dist>0.30 → 0
    score = float(np.clip((1 - dist / 0.30) * 100, 0, 100))
    return score, {"high52w": high52, "current": c, "distance_pct": dist}


# ── public ───────────────────────────────────────────────────────────────────


def compute_momentum(df: pd.DataFrame, index_df: pd.DataFrame | None = None) -> MomentumResult:
    """
    Compute Momentum sub-score from a normalized OHLCV DataFrame.

    Args:
        df: normalized OHLCV (date, open, high, low, close, volume)
        index_df: optional benchmark OHLCV for relative-strength computation
    Returns:
        MomentumResult with score, components, and unavailable list.
    """
    close = _safe_series(df, "close")
    if close is None:
        return MomentumResult(score=float("nan"), components={}, unavailable=list(WEIGHTS.keys()))

    index_close = _safe_series(index_df, "close") if index_df is not None else None

    trend_score, trend_det = _trend_alignment(close)
    rsi_score, rsi_val = _rsi(close)
    macd_score, macd_det = _macd(close)
    vol_score, vol_det = _volume_surge(df)
    rs_score, rs_det = _relative_strength(close, index_close)
    high_score, high_det = _high52w_proximity(close)

    raw: dict[str, float] = {
        "trend_alignment": trend_score,
        "rsi": rsi_score,
        "macd": macd_score,
        "volume": vol_score,
        "relative_strength": rs_score,
        "high52w": high_score,
    }

    unavailable = [k for k, v in raw.items() if np.isnan(v)]
    available = {k: v for k, v in raw.items() if not np.isnan(v)}

    if not available:
        return MomentumResult(score=float("nan"), components={}, unavailable=list(WEIGHTS.keys()))

    # Renormalize weights over available components
    total_w = sum(WEIGHTS[k] for k in available)
    score = sum(WEIGHTS[k] / total_w * v for k, v in available.items())

    return MomentumResult(
        score=round(score, 2),
        components={k: round(v, 2) for k, v in raw.items() if not np.isnan(v)},
        unavailable=unavailable,
        details={
            "trend": trend_det,
            "rsi_value": rsi_val,
            "macd": macd_det,
            "volume": vol_det,
            "relative_strength": rs_det,
            "high52w": high_det,
        },
    )
