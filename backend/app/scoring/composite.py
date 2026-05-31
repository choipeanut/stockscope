"""Composite scorer.

Full weights (10-factor):
  fundamental 0.22 | valuation 0.15 | supply_demand 0.11
  momentum    0.11 | macro     0.08 | risk         0.08
  market_sentiment 0.07 | analyst 0.08 | insider 0.06 | options 0.04

Data-coverage confidence penalty:
  핵심 팩터(fundamental+valuation)가 없을수록 composite에 할인 적용.
  신뢰도 = 0.55 + 0.45 * (가용_팩터_가중치 합계)
  - 10/10 팩터 (weight=1.00) → 신뢰도 1.00 → 패널티 없음
  - 7/10 팩터 (weight≈0.72) → 신뢰도 0.87 → 13% 감점
  - 기본 4팩터만 (weight≈0.42) → 신뢰도 0.74 → 26% 감점
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

FULL_WEIGHTS: dict[str, float] = {
    "fundamental":      0.22,
    "valuation":        0.15,
    "supply_demand":    0.11,
    "momentum":         0.11,
    "macro":            0.08,
    "risk":             0.08,
    "market_sentiment": 0.07,
    "analyst":          0.08,
    "insider":          0.06,
    "options":          0.04,
}


@dataclass
class CompositeResult:
    composite: float
    factors: dict[str, float | None]   # None = unavailable
    unavailable: list[str]
    renormalized: bool
    as_of: str
    details: dict[str, Any] = field(default_factory=dict)


def compute_composite(
    factor_scores: dict[str, float | None],
    as_of: str,
    details: dict[str, Any] | None = None,
) -> CompositeResult:
    """
    Compute weighted composite from factor_scores dict.
    Keys: fundamental, valuation, supply_demand, momentum, macro, risk.
    Value None means unavailable — weight is dropped, remainder renormalized,
    then a data-coverage confidence multiplier is applied.
    """
    available: dict[str, float] = {}
    unavailable: list[str] = []

    for factor, weight in FULL_WEIGHTS.items():
        val = factor_scores.get(factor)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            unavailable.append(factor)
        else:
            available[factor] = float(val)

    renormalized = len(unavailable) > 0

    if not available:
        return CompositeResult(
            composite=float("nan"),
            factors=factor_scores,
            unavailable=unavailable,
            renormalized=renormalized,
            as_of=as_of,
            details=details or {},
        )

    # 가용 팩터 가중치 합계 (0.0~1.0)
    available_weight = sum(FULL_WEIGHTS[f] for f in available)

    # 가중 평균 (가용 팩터 내에서 정규화)
    total_w = available_weight
    composite = sum(FULL_WEIGHTS[f] / total_w * v for f, v in available.items())

    # 데이터 신뢰도 패널티:
    # 팩터 가중치 커버리지가 낮을수록 점수 할인
    # confidence = 0.55 + 0.45 * available_weight
    #   - weight=1.00 (완전) → confidence=1.00 (패널티 없음)
    #   - weight=0.35 (모멘+매크로+리스크만) → confidence=0.71 (29% 할인)
    confidence = 0.55 + 0.45 * available_weight
    composite = composite * confidence

    return CompositeResult(
        composite=round(composite, 2),
        factors={k: (round(v, 2) if v is not None else None) for k, v in factor_scores.items()},
        unavailable=unavailable,
        renormalized=renormalized,
        as_of=as_of,
        details=details or {},
    )
