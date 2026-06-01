"""Event-driven catalyst scoring — earnings surprise + Claude disclosure reading.

The honest premise (see the AI-prediction discussion): raw price/fundamental
numbers don't beat the market short-term. Our one defensible edge is using
Claude to *read* fresh disclosures/earnings qualitatively — something a small
quant can't do cheaply — and combining that with the single most robust
short-horizon anomaly, post-earnings-announcement drift (PEAD).

A catalyst score has two parts:

  1. EARNINGS SURPRISE (quantitative, point-in-time): year-over-year growth of
     revenue and operating income from the most recent DART annual report that
     was already public. We don't have analyst consensus for KR names, so YoY
     acceleration is the proxy. Strong positive YoY → drift tailwind.

  2. CATALYST READ (qualitative, Claude): Claude classifies the most recent
     disclosures into a structured signal — guidance up/down, contract win,
     capacity expansion, dilution (유상증자), buyback, litigation — with a
     direction, materiality and a one-line thesis. This is the part that's hard
     to replicate and where the edge lives.

Both degrade gracefully: no DART → surprise is neutral; no Claude key / no
disclosures → catalyst read is neutral. The combined score is always in [0,100]
with 50 = neutral, and every pick carries an explicit, *pre-registered* thesis
so the tracking loop validates a hypothesis instead of inventing a hindsight
story.
"""
from __future__ import annotations

import json
import logging
import math
import os

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"

# How much each part moves the score away from the neutral 50.
_SURPRISE_WEIGHT = 0.45
_CATALYST_WEIGHT = 0.55


# ── 1. Earnings surprise (quantitative, point-in-time) ───────────────────────

def _yoy(curr: float | None, prev: float | None) -> float | None:
    """Year-over-year growth fraction, sign-aware. None if not computable."""
    if curr is None or prev is None:
        return None
    try:
        c, p = float(curr), float(prev)
    except (TypeError, ValueError):
        return None
    if math.isnan(c) or math.isnan(p) or p == 0:
        return None
    return (c - p) / abs(p)


def earnings_surprise(dart_history) -> dict:
    """Point-in-time earnings-surprise sub-score from a DART history frame.

    Uses the most recent ALREADY-PUBLIC annual report (the caller passes the
    history; `available_from` gating is the caller's job, but the row also
    carries prev_* so YoY needs no extra lookup).

    Returns {score: 0-100, revenue_yoy, op_yoy, fiscal_year, available}.
    """
    out = {
        "score": 50.0, "revenue_yoy": None, "op_yoy": None,
        "fiscal_year": None, "available": False,
    }
    if dart_history is None or getattr(dart_history, "empty", True):
        return out

    # most recent report by available_from (history is sorted ascending)
    rec = dart_history.iloc[-1]
    rev_yoy = _yoy(rec.get("revenue"), rec.get("prev_revenue"))
    op_yoy = _yoy(rec.get("op_income"), rec.get("prev_op_income"))
    out["revenue_yoy"] = rev_yoy
    out["op_yoy"] = op_yoy
    out["fiscal_year"] = (
        int(rec.get("fiscal_year")) if rec.get("fiscal_year") is not None else None
    )

    if rev_yoy is None and op_yoy is None:
        return out

    # Operating income YoY carries more signal for drift than revenue; weight it.
    # Map each YoY through a soft curve: +30% → ~+25 pts, −30% → ~−25 pts,
    # saturating so a single blowout number can't dominate.
    def pts(yoy: float | None) -> float:
        if yoy is None:
            return 0.0
        return 25.0 * math.tanh(yoy / 0.30)

    # 0.4*revenue + 0.6*operating-income, each already soft-capped to ~[-25,25]
    delta = 0.40 * pts(rev_yoy) + 0.60 * pts(op_yoy)
    out["score"] = float(max(0.0, min(100.0, 50.0 + delta)))
    out["available"] = True
    return out


# ── 2. Catalyst read (qualitative, Claude) ───────────────────────────────────

_CATALYST_SYSTEM = """당신은 한국/미국 주식의 공시·뉴스에서 '주가 촉매(catalyst)'를 추출하는 애널리스트입니다.
제공된 최근 공시/뉴스 제목만 보고, 향후 수 주간 주가에 작용할 촉매의 성격을 분류하세요.
추측성 예측이 아니라, 공시에 드러난 '사실의 성격'을 분류하는 것이 목표입니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "direction": "bullish" | "bearish" | "neutral",
  "materiality": "high" | "medium" | "low",
  "catalyst_type": "guidance_up|guidance_down|contract_win|capacity_expansion|earnings_beat|earnings_miss|buyback|dividend|equity_dilution|litigation|mna|none 중 하나",
  "score": 0~100 정수,   // 50=중립, 100=강한 호재, 0=강한 악재
  "thesis": "한 줄 근거 (한국어, 60자 이내, 어떤 공시가 왜 촉매인지)"
}

기준:
- 가이던스 상향/대형 수주/증설/자사주 소각/실적 대폭 상회 → bullish, score 70~95
- 배당 증가/소규모 수주/신제품 → bullish, score 55~70
- 단순·정기 공시, 재료 없음 → neutral, score 45~55, catalyst_type=none
- 유상증자(희석)/소송/실적 하회/가이던스 하향 → bearish, score 5~45
공시가 비어 있거나 촉매가 없으면 neutral/none/50을 반환하세요."""


def catalyst_read(ticker: str, market: str, disclosures: list[dict],
                  news: list[dict] | None = None) -> dict:
    """Claude-classified catalyst from recent disclosures/news titles.

    Returns {direction, materiality, catalyst_type, score(0-100), thesis,
    available}. Neutral (score 50) when no key / no items / parse failure.
    """
    neutral = {
        "direction": "neutral", "materiality": "low", "catalyst_type": "none",
        "score": 50, "thesis": "", "available": False,
    }
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {**neutral, "reason": "ANTHROPIC_API_KEY not set"}

    items = list(disclosures or []) + list(news or [])
    if not items:
        return {**neutral, "reason": "no disclosures/news"}

    lines = [f"종목: {ticker} ({market})", ""]
    if disclosures:
        lines.append("=== 최근 공시 (DART) ===")
        for d in disclosures[:8]:
            lines.append(f"- [{d.get('published', '')}] {d.get('title', '')}")
        lines.append("")
    if news:
        lines.append("=== 최근 뉴스 ===")
        for n in news[:6]:
            lines.append(f"- {n.get('title', '')}")
    prompt = "\n".join(lines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system=_CATALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        parsed["available"] = True
        # clamp/normalise score
        try:
            parsed["score"] = int(max(0, min(100, int(parsed.get("score", 50)))))
        except (TypeError, ValueError):
            parsed["score"] = 50
        return parsed
    except Exception as e:
        logger.warning("catalyst_read failed %s: %s", ticker, e)
        return {**neutral, "reason": str(e)}


# ── 3. Combined catalyst score ───────────────────────────────────────────────

def catalyst_score(ticker: str, market: str, dart_history=None,
                   disclosures: list[dict] | None = None,
                   news: list[dict] | None = None,
                   use_claude: bool = True) -> dict:
    """Combine earnings surprise + Claude catalyst read into one 0-100 score.

    50 = neutral. The pre-registered `thesis` is what the tracking loop later
    validates. Both parts degrade to neutral independently.
    """
    surprise = earnings_surprise(dart_history)
    read = (
        catalyst_read(ticker, market, disclosures or [], news)
        if use_claude else
        {"direction": "neutral", "materiality": "low", "catalyst_type": "none",
         "score": 50, "thesis": "", "available": False}
    )

    # Weighted blend around the neutral midpoint of 50.
    s_delta = surprise["score"] - 50.0
    c_delta = read["score"] - 50.0
    combined = 50.0 + _SURPRISE_WEIGHT * s_delta + _CATALYST_WEIGHT * c_delta
    combined = float(max(0.0, min(100.0, combined)))

    # Build a single human thesis from whichever parts fired.
    thesis_parts: list[str] = []
    if read.get("thesis"):
        thesis_parts.append(read["thesis"])
    if surprise.get("available"):
        rev, op = surprise.get("revenue_yoy"), surprise.get("op_yoy")
        bits = []
        if rev is not None:
            bits.append(f"매출 YoY {rev * 100:+.0f}%")
        if op is not None:
            bits.append(f"영업익 YoY {op * 100:+.0f}%")
        if bits:
            thesis_parts.append(" · ".join(bits))
    thesis = " | ".join(thesis_parts) if thesis_parts else "뚜렷한 촉매 없음"

    return {
        "ticker": ticker,
        "market": market,
        "score": round(combined, 1),
        "thesis": thesis,
        "surprise": surprise,
        "catalyst": read,
    }
