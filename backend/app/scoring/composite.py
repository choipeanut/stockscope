"""Composite scorer.

M1: uses only price-computable factors (momentum + price-derived risk partial).
Other factors are explicitly marked unavailable — never zero-filled.

Full weights (ANALYSIS_SPEC):
  fundamental 0.30 | valuation 0.20 | supply_demand 0.15
  momentum    0.15 | macro     0.10 | risk         0.10
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

FULL_WEIGHTS: dict[str, float] = {
    "fundamental": 0.30,
    "valuation": 0.20,
    "supply_demand": 0.15,
    "momentum": 0.15,
    "macro": 0.10,
    "risk": 0.10,
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
    Value None means unavailable — weight is dropped and remainder renormalized.
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

    total_w = sum(FULL_WEIGHTS[f] for f in available)
    composite = sum(FULL_WEIGHTS[f] / total_w * v for f, v in available.items())

    return CompositeResult(
        composite=round(composite, 2),
        factors={k: (round(v, 2) if v is not None else None) for k, v in factor_scores.items()},
        unavailable=unavailable,
        renormalized=renormalized,
        as_of=as_of,
        details=details or {},
    )
