"""Scenario generation (bull/bear/neutral) per ANALYSIS_SPEC §Scenario Generation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Scenario:
    stance: str                       # "bull" | "bear" | "neutral"
    probability_hint: str             # "low" | "medium" | "high"
    reasons: list[str]
    watch_conditions: list[str]


def generate_scenarios(
    factors: dict,          # factor_name → score (0-100 or None)
    momentum_detail: dict,
    fund_data: dict | None = None,
    flow_data: dict | None = None,
    macro_data: dict | None = None,
    risk_data: dict | None = None,
) -> list[Scenario]:
    bull_reasons: list[str] = []
    bear_reasons: list[str] = []
    neutral_reasons: list[str] = []
    bull_watch: list[str] = []
    bear_watch: list[str] = []
    neutral_watch: list[str] = []

    # ── Momentum signals ────────────────────────────────────────────
    mom = factors.get("momentum")
    if mom is not None:
        comps = momentum_detail.get("components", {})
        trend = comps.get("trend_alignment")
        rsi = comps.get("rsi")
        vol = comps.get("volume")
        rs = comps.get("relative_strength")

        if trend is not None and trend >= 80:
            bull_reasons.append(f"MA 추세 정렬 강세 (점수 {trend:.0f}/100)")
        elif trend is not None and trend <= 30:
            bear_reasons.append(f"MA 추세 붕괴 (점수 {trend:.0f}/100)")

        if vol is not None and vol >= 80:
            bull_reasons.append(f"거래량 돌파 확인 (점수 {vol:.0f}/100)")

        if rs is not None and rs >= 70:
            bull_reasons.append(f"시장 대비 상대강도 우위 ({rs:.0f}/100)")
        elif rs is not None and rs <= 30:
            bear_reasons.append(f"시장 대비 상대강도 열세 ({rs:.0f}/100)")

        if rsi is not None and rsi <= 20:
            bear_reasons.append(f"RSI 과매수 부근 ({rsi:.0f}/100)")

        bull_watch.append("20일선 이탈 여부 모니터링")
        bear_watch.append("20일선 회복 시 반전 신호 확인")

    # ── Fundamental signals ─────────────────────────────────────────
    fund = factors.get("fundamental")
    if fund is not None:
        if fund >= 70:
            bull_reasons.append(f"펀더멘털 양호 (종합 {fund:.0f}/100)")
        elif fund <= 35:
            bear_reasons.append(f"펀더멘털 취약 (종합 {fund:.0f}/100)")

        if fund_data:
            rg = fund_data.get("revenue_growth")
            if rg is not None and rg > 15:
                bull_reasons.append(f"매출 성장률 {rg:.1f}% YoY")
            elif rg is not None and rg < -10:
                bear_reasons.append(f"매출 역성장 {rg:.1f}% YoY")

            ocf = fund_data.get("operating_cf")
            if ocf is not None and ocf < 0:
                bear_reasons.append("영업현금흐름 음수 — 현금 소진 위험")

        neutral_watch.append("다음 분기 실적 발표 시 펀더멘털 재점검")

    # ── Valuation signals ───────────────────────────────────────────
    val = factors.get("valuation")
    if val is not None:
        if val >= 75:
            bull_reasons.append(f"밸류에이션 저평가 구간 ({val:.0f}/100)")
        elif val <= 30:
            bear_reasons.append(f"밸류에이션 고평가 부담 ({val:.0f}/100)")
            neutral_reasons.append("고밸류+강한 펀더멘털 = 중립 유지")

    # ── Supply/demand signals ───────────────────────────────────────
    sd = factors.get("supply_demand")
    if sd is not None:
        if sd >= 70:
            bull_reasons.append(f"외국인·기관 순매수 우세 (수급 {sd:.0f}/100)")
        elif sd <= 35:
            bear_reasons.append(f"수급 약세 — 외국인·기관 이탈 ({sd:.0f}/100)")

        if flow_data and flow_data.get("short_ratio") is not None:
            sr = flow_data["short_ratio"]
            if sr > 10:
                bear_reasons.append(f"공매도 비중 높음 ({sr:.1f}%)")
            bull_watch.append("외국인 5일 순매수 전환 확인")

    # ── Macro signals ───────────────────────────────────────────────
    mac = factors.get("macro")
    if mac is not None:
        if macro_data:
            regime = macro_data.get("regime", "")
            if regime in ("확장", "회복"):
                bull_reasons.append(f"거시환경 우호적 — {regime} 국면")
            elif regime in ("침체", "둔화"):
                bear_reasons.append(f"거시 역풍 — {regime} 국면")

            vix = macro_data.get("vix")
            if vix and vix > 30:
                bear_reasons.append(f"VIX 급등 ({vix:.0f}) — 시장 불확실성 높음")

    # ── Risk signals ────────────────────────────────────────────────
    risk = factors.get("risk")
    if risk is not None and risk <= 40:
        bear_reasons.append(f"리스크 점수 낮음 ({risk:.0f}/100) — 부채·감사 위험 주의")
        bear_watch.append("부채비율 추이 및 이자보상배율 확인")

    # ── Neutral condition ───────────────────────────────────────────
    has_conflict = (
        (fund is not None and fund >= 70 and val is not None and val <= 35)
        or (sd is not None and sd <= 35 and mom is not None and mom >= 70)
    )
    if has_conflict:
        neutral_reasons.append("강한 펀더멘털이나 밸류 부담 또는 수급 약세 — 이벤트 대기")
        neutral_watch.append("주가 핵심 지지선 및 다음 실적 이벤트 모니터링")

    # ── Probability hints ───────────────────────────────────────────
    composite = sum(v for v in factors.values() if v is not None)
    n = sum(1 for v in factors.values() if v is not None)
    avg = composite / n if n > 0 else 50

    if avg >= 65:
        bull_prob, bear_prob = "medium", "low"
    elif avg <= 40:
        bull_prob, bear_prob = "low", "medium"
    else:
        bull_prob, bear_prob = "low", "low"

    return [
        Scenario(
            stance="bull",
            probability_hint=bull_prob,
            reasons=bull_reasons or ["현재 명확한 상승 트리거 미확인"],
            watch_conditions=bull_watch or ["거래량 동반 상승 돌파 확인"],
        ),
        Scenario(
            stance="bear",
            probability_hint=bear_prob,
            reasons=bear_reasons or ["현재 명확한 하락 트리거 미확인"],
            watch_conditions=bear_watch or ["핵심 지지선 이탈 여부 모니터링"],
        ),
        Scenario(
            stance="neutral",
            probability_hint="medium",
            reasons=neutral_reasons or ["상승·하락 신호 혼재 — 관망 유지"],
            watch_conditions=neutral_watch or ["다음 실적 발표 또는 수급 변화 확인"],
        ),
    ]
