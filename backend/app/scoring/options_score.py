"""옵션 시장 감성 점수 (0-100).

구성:
  Put/Call 거래량 비율  70%  — PCR 낮을수록 강세 심리
  내재변동성 (IV)       30%  — 과도하게 높으면 공포 신호

PCR 해석:
  < 0.6  → 콜 쏠림, 강세 (85-100)
  0.6-0.8 → 약한 강세 (65-85)
  0.8-1.0 → 중립 (50-65)
  1.0-1.2 → 약한 약세 (35-50)
  > 1.2  → 풋 쏠림, 약세 (0-35)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class OptionsResult:
    score: float
    components: dict[str, float] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)


def _pcr_score(pcr: float) -> float:
    """Put/Call 비율 → 0-100 점수 (낮을수록 강세)."""
    if pcr < 0.4:
        return 100.0
    elif pcr < 0.6:
        return 85 + (0.6 - pcr) / 0.2 * 15
    elif pcr < 0.8:
        return 65 + (0.8 - pcr) / 0.2 * 20
    elif pcr < 1.0:
        return 50 + (1.0 - pcr) / 0.2 * 15
    elif pcr < 1.2:
        return 35 + (1.2 - pcr) / 0.2 * 15
    elif pcr < 1.5:
        return 15 + (1.5 - pcr) / 0.3 * 20
    else:
        return max(0.0, 15 - (pcr - 1.5) * 10)


def _iv_score(iv: float) -> float:
    """내재변동성 → 0-100 점수 (낮을수록 안정, 너무 낮으면 과신)."""
    # IV: 0~1 범위 (e.g. 0.25 = 25%)
    if iv < 0.15:
        return 60.0   # 매우 낮음 — 과신/거품 가능성
    elif iv < 0.25:
        return 70.0   # 낮음 — 안정적
    elif iv < 0.35:
        return 55.0   # 보통
    elif iv < 0.5:
        return 40.0   # 높음 — 불확실
    elif iv < 0.7:
        return 25.0   # 매우 높음 — 공포
    else:
        return 10.0   # 극단적 공포


def compute_options(data: dict) -> OptionsResult:
    if not data.get("available"):
        return OptionsResult(score=float("nan"), unavailable=["options"])

    components: dict[str, float] = {}
    scores: list[tuple[float, float]] = []

    # ── PCR (70%) ────────────────────────────────────────────────────
    pcr = data.get("put_call_volume_ratio")
    if pcr is None:
        pcr = data.get("put_call_oi_ratio")   # fallback to OI ratio

    if pcr is not None:
        try:
            pcr_s = max(0.0, min(100.0, _pcr_score(float(pcr))))
            components["pcr"] = round(pcr_s, 2)
            scores.append((pcr_s, 0.70))
        except Exception:
            pass

    # ── IV (30%) ─────────────────────────────────────────────────────
    iv = data.get("avg_iv")
    if iv is not None:
        try:
            iv_s = max(0.0, min(100.0, _iv_score(float(iv))))
            components["iv"] = round(iv_s, 2)
            scores.append((iv_s, 0.30))
        except Exception:
            pass

    if not scores:
        return OptionsResult(score=float("nan"), unavailable=["options"])

    total_w = sum(w for _, w in scores)
    final = sum(sc * w for sc, w in scores) / total_w
    return OptionsResult(score=round(max(0.0, min(100.0, final)), 2), components=components)
