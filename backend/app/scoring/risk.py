"""Risk sub-score (weight 0.10) — inverted: 100 = safest.

Starts at 100 and subtracts penalties per ANALYSIS_SPEC §Risk:
  부채 위험      −25  high debt / interest coverage < 1
  오버행         −20  CB/BW outstanding
  회계 위험      −30  bad audit opinion
  변동성         −15  ATR% high / beta high
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


@dataclass
class RiskResult:
    score: float          # 100 = safest (inverted)
    penalties: dict[str, float]
    partial: bool = False  # True when DART data unavailable
    components: dict = field(default_factory=dict)


def compute_risk(data: dict, fund_data: dict | None = None) -> RiskResult:
    score = 100.0
    penalties: dict[str, float] = {}
    partial = not data.get("dart_available", False)

    # Volatility penalty (ATR%)
    atr = _nav(data.get("atr_pct"))
    if atr is not None:
        if atr > 5:
            p = min(15.0, (atr - 5) * 3)
            score -= p
            penalties["volatility"] = p
        elif atr > 3:
            p = (atr - 3) * 3
            score -= p
            penalties["volatility"] = p

    # Beta penalty
    beta = _nav(data.get("beta"))
    if beta is not None and beta > 1.5:
        p = min(10.0, (beta - 1.5) * 10)
        score -= p
        penalties["high_beta"] = p

    # Debt penalty (from fundamental data if available)
    if fund_data:
        debt_ratio = _nav(fund_data.get("debt_ratio"))
        ic = _nav(fund_data.get("interest_coverage"))
        if debt_ratio is not None and debt_ratio > 300:
            p = min(25.0, (debt_ratio - 300) / 100 * 10)
            score -= p
            penalties["high_debt"] = p
        if ic is not None and ic < 1:
            score -= 20
            penalties["low_interest_coverage"] = 20.0

    # DART-sourced penalties
    if data.get("high_debt"):
        score -= 20
        penalties["high_debt_disclosure"] = 20.0

    if data.get("audit_opinion_bad"):
        score -= 30
        penalties["bad_audit"] = 30.0

    if data.get("cb_bw_outstanding"):
        score -= 20
        penalties["overhang"] = 20.0

    return RiskResult(
        score=round(max(0.0, min(100.0, score)), 2),
        penalties=penalties,
        partial=partial,
        components={"atr_pct": atr, "beta": beta},
    )
