"""Valuation sub-score (weight 0.20) per ANALYSIS_SPEC §Valuation.

Components:
  PER         0.25  lower better (sector-relative → percentile inverted)
  PBR         0.15  lower better (but low+low-ROE not rewarded)
  PSR         0.15  lower better
  EV/EBITDA   0.20  lower better
  배당수익률   0.10  higher better
  과거 위치    0.15  current vs 5y avg PER percentile — lower-in-range better
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

WEIGHTS = {
    "per": 0.25,
    "pbr": 0.15,
    "psr": 0.15,
    "ev_ebitda": 0.20,
    "dividend_yield": 0.10,
    "hist_position": 0.15,
}

# Reasonable banded thresholds for absolute scoring
# (sector-relative would need peer data; we use broad market bands as proxy)
_PER_BANDS = [(0, 10, 100), (10, 15, 90), (15, 20, 75), (20, 30, 55),
              (30, 50, 30), (50, 100, 10), (100, 9999, 0)]
_PBR_BANDS = [(0, 1, 100), (1, 2, 85), (2, 3, 65), (3, 5, 40), (5, 10, 20), (10, 9999, 5)]
_PSR_BANDS = [(0, 1, 100), (1, 3, 80), (3, 6, 55), (6, 10, 30), (10, 9999, 10)]
_EV_BANDS = [(0, 8, 100), (8, 12, 80), (12, 20, 55), (20, 30, 30), (30, 9999, 10)]


def _band(val: float, bands: list) -> float:
    for lo, hi, score in bands:
        if lo <= val < hi:
            return float(score)
    return 0.0


def _score_per(per: float | None) -> float | None:
    if per is None or math.isnan(per) or per <= 0:
        return None
    return _band(per, _PER_BANDS)


def _score_pbr(pbr: float | None) -> float | None:
    if pbr is None or math.isnan(pbr) or pbr <= 0:
        return None
    return _band(pbr, _PBR_BANDS)


def _score_psr(psr: float | None) -> float | None:
    if psr is None or math.isnan(psr) or psr <= 0:
        return None
    return _band(psr, _PSR_BANDS)


def _score_ev_ebitda(ev: float | None) -> float | None:
    if ev is None or math.isnan(ev) or ev <= 0:
        return None
    return _band(ev, _EV_BANDS)


def _score_div_yield(dy: float | None) -> float | None:
    """dy in percent (e.g. 2.5 for 2.5%)."""
    if dy is None or math.isnan(dy) or dy < 0:
        return None
    return float(min(100.0, dy * 15))  # 0% → 0, ~6.5% → 100


def _score_hist_position(per_5y_pct: float | None) -> float | None:
    """lower percentile (cheap vs history) = higher score."""
    if per_5y_pct is None:
        return None
    return float(100 - per_5y_pct)


@dataclass
class ValuationResult:
    score: float
    components: dict[str, float]
    unavailable: list[str] = field(default_factory=list)


def compute_valuation(data: dict) -> ValuationResult:
    """data = output of get_valuation()."""
    raw: dict[str, float | None] = {
        "per": _score_per(data.get("per")),
        "pbr": _score_pbr(data.get("pbr")),
        "psr": _score_psr(data.get("psr")),
        "ev_ebitda": _score_ev_ebitda(data.get("ev_ebitda")),
        "dividend_yield": _score_div_yield(data.get("dividend_yield")),
        "hist_position": _score_hist_position(data.get("per_5y_pct")),
    }

    unavailable = [k for k, v in raw.items() if v is None]
    available = {k: v for k, v in raw.items() if v is not None}

    if not available:
        return ValuationResult(score=float("nan"), components={}, unavailable=list(WEIGHTS))

    total_w = sum(WEIGHTS[k] for k in available)
    score = sum(WEIGHTS[k] / total_w * v for k, v in available.items())

    return ValuationResult(
        score=round(score, 2),
        components={k: round(v, 2) for k, v in available.items()},
        unavailable=unavailable,
    )
