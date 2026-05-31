"""애널리스트 컨센서스 점수 (0-100).

구성:
  컨센서스 점수   60%  — 투자의견 분포 가중 평균
  목표주가 괴리   30%  — 현재가 대비 상승여력
  등급 변화 모멘텀 10% — 최근 90일 업그레이드 vs 다운그레이드
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class AnalystResult:
    score: float
    components: dict[str, float] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)


def _nav(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def compute_analyst(data: dict) -> AnalystResult:
    if not data.get("available"):
        return AnalystResult(score=float("nan"), unavailable=["analyst"])

    components: dict[str, float] = {}
    scores: list[tuple[float, float]] = []  # (score, weight)

    # ── 1. 컨센서스 점수 (60%) ───────────────────────────────────────
    sb  = int(data.get("strong_buy",  0) or 0)
    b   = int(data.get("buy",         0) or 0)
    h   = int(data.get("hold",        0) or 0)
    s   = int(data.get("sell",        0) or 0)
    ss  = int(data.get("strong_sell", 0) or 0)
    total = sb + b + h + s + ss

    if total > 0:
        # strongBuy=100, buy=75, hold=50, sell=25, strongSell=0
        consensus = (sb * 100 + b * 75 + h * 50 + s * 25 + ss * 0) / total
        components["consensus"] = round(consensus, 2)
        scores.append((consensus, 0.60))

    # ── 2. 목표주가 상승여력 (30%) ───────────────────────────────────
    upside = _nav(data.get("upside_pct"))
    if upside is not None:
        # upside ≥ 30% → 100, 15-30% → 70-100, 0-15% → 40-70
        # 0 → 40, -10% → 20, ≤ -20% → 0
        if upside >= 30:
            upside_score = 100.0
        elif upside >= 15:
            upside_score = 70 + (upside - 15) / 15 * 30
        elif upside >= 0:
            upside_score = 40 + upside / 15 * 30
        elif upside >= -20:
            upside_score = max(0, 40 + upside * 2)
        else:
            upside_score = 0.0
        upside_score = max(0.0, min(100.0, upside_score))
        components["upside"] = round(upside_score, 2)
        scores.append((upside_score, 0.30))

    # ── 3. 등급 변화 모멘텀 (10%) ────────────────────────────────────
    up   = int(data.get("upgrades_3m",   0) or 0)
    down = int(data.get("downgrades_3m", 0) or 0)
    if up + down > 0:
        change_ratio = up / (up + down)          # 0~1
        change_score = change_ratio * 100
        components["rating_momentum"] = round(change_score, 2)
        scores.append((change_score, 0.10))

    if not scores:
        return AnalystResult(score=float("nan"), unavailable=["analyst"])

    total_w = sum(w for _, w in scores)
    final = sum(sc * w for sc, w in scores) / total_w
    final = max(0.0, min(100.0, final))

    return AnalystResult(score=round(final, 2), components=components)
