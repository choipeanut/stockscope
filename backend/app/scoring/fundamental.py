"""Fundamental sub-score (weight 0.30) per ANALYSIS_SPEC §Fundamental.

Components:
  성장성  0.25  revenue_growth YoY, eps_growth
  수익성  0.25  op_margin, ROE, ROA
  안정성  0.20  debt_ratio (lower better), interest_coverage (higher better)
  현금흐름 0.20  operating_cf, FCF  (OCF<0 or FCF<0 caps ≤ 30)
  주주환원 0.10  dividend_payout, buyback
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

WEIGHTS = {
    "growth": 0.25,
    "profitability": 0.25,
    "stability": 0.20,
    "cashflow": 0.20,
    "shareholder_return": 0.10,
}


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _pct_to_score(pct: float | None, lo: float = -20, hi: float = 40) -> float | None:
    """Map a percent growth/margin to 0-100 via linear clamp."""
    if pct is None:
        return None
    return float(max(0.0, min(100.0, (pct - lo) / (hi - lo) * 100)))


def _score_growth(data: dict) -> float | None:
    rg = _pct_to_score(_nav(data.get("revenue_growth")), lo=-30, hi=50)
    eg = _pct_to_score(_nav(data.get("eps_growth")), lo=-30, hi=50)
    vals = [v for v in [rg, eg] if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _score_profitability(data: dict) -> float | None:
    op = _pct_to_score(_nav(data.get("op_margin")), lo=-10, hi=30)
    roe = _pct_to_score(_nav(data.get("roe")), lo=-5, hi=25)
    roa = _pct_to_score(_nav(data.get("roa")), lo=-3, hi=15)
    vals = [v for v in [op, roe, roa] if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _score_stability(data: dict) -> float | None:
    debt = _nav(data.get("debt_ratio"))
    ic = _nav(data.get("interest_coverage"))
    scores = []
    if debt is not None:
        # debt_ratio: 0–50 → 100, 50–100 → 70, 100–200 → 40, >200 → 10
        if debt < 50:
            scores.append(100.0)
        elif debt < 100:
            scores.append(70.0)
        elif debt < 200:
            scores.append(40.0)
        else:
            scores.append(10.0)
    if ic is not None:
        # interest_coverage: <1 → 0 (dangerous), 1–3 → 40, 3–10 → 80, >10 → 100
        if ic < 1:
            scores.append(0.0)
        elif ic < 3:
            scores.append(40.0)
        elif ic < 10:
            scores.append(80.0)
        else:
            scores.append(100.0)
    return round(sum(scores) / len(scores), 2) if scores else None


def _score_cashflow(data: dict) -> float | None:
    ocf = _nav(data.get("operating_cf"))
    fcf = _nav(data.get("fcf"))
    if ocf is None and fcf is None:
        return None
    # Negative OCF or FCF caps component at 30
    if (ocf is not None and ocf < 0) or (fcf is not None and fcf < 0):
        return 30.0
    return 80.0  # positive cashflow — good signal (absolute magnitude not normalized without peers)


def _score_shareholder_return(data: dict) -> float | None:
    dp = _nav(data.get("dividend_payout"))
    bb = _nav(data.get("buyback"))
    scores = []
    if dp is not None:
        # 0–20%: 40, 20–50%: 80, 50–80%: 100, >80%: 70 (too high = unsustainable)
        if dp < 20:
            scores.append(40.0)
        elif dp < 50:
            scores.append(80.0)
        elif dp < 80:
            scores.append(100.0)
        else:
            scores.append(70.0)
    if bb is not None and bb > 0:
        scores.append(80.0)
    return round(sum(scores) / len(scores), 2) if scores else None


@dataclass
class FundamentalResult:
    score: float
    components: dict[str, float]
    unavailable: list[str] = field(default_factory=list)
    key_required: str | None = None


def compute_fundamental(data: dict) -> FundamentalResult:
    if not data.get("available", False):
        return FundamentalResult(
            score=float("nan"), components={},
            unavailable=list(WEIGHTS),
            key_required=data.get("key_required"),
        )

    raw: dict[str, float | None] = {
        "growth": _score_growth(data),
        "profitability": _score_profitability(data),
        "stability": _score_stability(data),
        "cashflow": _score_cashflow(data),
        "shareholder_return": _score_shareholder_return(data),
    }

    unavailable = [k for k, v in raw.items() if v is None]
    available = {k: v for k, v in raw.items() if v is not None}

    if not available:
        return FundamentalResult(
            score=float("nan"), components={}, unavailable=list(WEIGHTS)
        )

    total_w = sum(WEIGHTS[k] for k in available)
    score = sum(WEIGHTS[k] / total_w * v for k, v in available.items())

    return FundamentalResult(
        score=round(score, 2),
        components={k: round(v, 2) for k, v in available.items()},
        unavailable=unavailable,
    )
