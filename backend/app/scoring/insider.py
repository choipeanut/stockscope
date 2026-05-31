"""내부자 거래 점수 (0-100).

임원·대주주의 순매수 비중이 클수록 높은 점수.
  - 순매수 우위: 60~100
  - 중립 (거래 없음): 50
  - 순매도 우위: 0~40
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class InsiderResult:
    score: float
    components: dict[str, float] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)


def compute_insider(data: dict) -> InsiderResult:
    if not data.get("available"):
        return InsiderResult(score=float("nan"), unavailable=["insider"])

    buy_count  = int(data.get("buy_count",  0) or 0)
    sell_count = int(data.get("sell_count", 0) or 0)
    buy_val    = float(data.get("buy_value",  0) or 0)
    sell_val   = float(data.get("sell_value", 0) or 0)
    total_cnt  = buy_count + sell_count
    total_val  = buy_val + sell_val

    # 거래 없음 → 중립
    if total_cnt == 0:
        return InsiderResult(score=50.0, components={"note": 50.0})

    components: dict[str, float] = {}

    # ── 건수 비율 점수 ────────────────────────────────────────────────
    count_ratio = buy_count / total_cnt          # 0(all sell) ~ 1(all buy)
    # 0→0, 0.5→50, 1→100 (선형)
    count_score = count_ratio * 100
    components["count_ratio"] = round(count_score, 2)

    # ── 금액 비율 점수 ────────────────────────────────────────────────
    if total_val > 0:
        val_ratio   = buy_val / total_val
        val_score   = val_ratio * 100
    else:
        val_score   = 50.0
    components["value_ratio"] = round(val_score, 2)

    # ── 순매수 절대 규모 보너스/패널티 ───────────────────────────────
    net = buy_val - sell_val
    if total_val > 0:
        net_pct = net / total_val               # -1 ~ +1
        # +1 → +10점 보너스, -1 → -10점 패널티
        magnitude_adj = net_pct * 10
    else:
        magnitude_adj = 0.0
    components["net_magnitude_adj"] = round(magnitude_adj, 2)

    # 최종 점수: 건수 50% + 금액 50%, 규모 보정 적용
    base = 0.50 * count_score + 0.50 * val_score
    final = max(0.0, min(100.0, base + magnitude_adj))

    return InsiderResult(score=round(final, 2), components=components)
