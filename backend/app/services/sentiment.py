"""뉴스·공시·거시환경 감성 분석 — Claude Haiku 사용."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"  # 빠르고 저렴, 한국어 우수

_SYSTEM = """당신은 금융 뉴스·공시·거시환경 감성 분석 전문가입니다.
종목 뉴스/공시와 거시 환경 뉴스를 종합 분석하여 해당 종목의 투자 점수 영향을 평가하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "sentiment": "positive" | "negative" | "neutral",
  "score_delta": -20 ~ +20 사이의 정수,
  "confidence": "high" | "medium" | "low",
  "summary": "한 줄 요약 (한국어, 50자 이내)",
  "key_signals": ["신호1", "신호2"]  // 최대 3개, 한국어
}

score_delta 기준 (종목 직접 뉴스 우선):
- 실적 대폭 상회, 대규모 자사주 소각, M&A 성공 → +15 ~ +20
- 실적 소폭 상회, 배당 증가, 신제품 출시 → +5 ~ +14
- 중립적 뉴스, 단순 공시 → -4 ~ +4
- 실적 소폭 하회, 소송 제기, 경영진 변경 → -5 ~ -14
- 분식회계, 상장폐지 위기, 대규모 손실 → -15 ~ -20

거시 환경 보조 반영 (종목 직접 뉴스가 약할 때):
- 금리 인하 기대, 무역협상 타결, 경기 호조 → +3 ~ +8
- 금리 인상, 무역전쟁 심화, 지정학적 위기 → -3 ~ -8
- 불확실성 지속, 혼조세 → -2 ~ +2

종목 직접 뉴스가 있으면 그것을 우선시하고, 거시 뉴스는 보조 신호로만 사용하세요."""


def analyze_sentiment(
    ticker: str,
    market: str,
    news_items: list[dict],
    disclosures: list[dict],
    macro_news: list[dict] | None = None,
) -> dict:
    """
    뉴스·공시·거시환경을 Claude로 분석하여 점수 보정값 반환.

    Returns:
        {
          sentiment: str,
          score_delta: int,
          confidence: str,
          summary: str,
          key_signals: list[str],
          available: bool,
        }
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _unavailable("ANTHROPIC_API_KEY not set")

    macro_news = macro_news or []
    all_items = disclosures + news_items + macro_news
    if not all_items:
        return _unavailable("no items to analyze")

    # 입력 텍스트 구성
    lines = [f"종목: {ticker} ({market})", ""]

    if disclosures:
        lines.append("=== 최근 공시 ===")
        for d in disclosures[:5]:
            lines.append(f"- [{d.get('published', '')}] {d.get('title', '')}")
        lines.append("")

    if news_items:
        lines.append("=== 종목 직접 뉴스 ===")
        for n in news_items[:8]:
            lines.append(f"- [{n.get('source', '')}] {n.get('title', '')}")
        lines.append("")

    if macro_news:
        lines.append("=== 거시 환경 뉴스 (국제 정세·금리·무역 등) ===")
        for m in macro_news[:8]:
            lines.append(f"- [{m.get('source', '')}] {m.get('title', '')}")

    prompt = "\n".join(lines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # JSON 파싱
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["available"] = True
        return result

    except Exception as e:
        logger.warning("sentiment analysis failed: %s", e)
        return _unavailable(str(e))


def _unavailable(reason: str) -> dict:
    return {
        "sentiment": "neutral",
        "score_delta": 0,
        "confidence": "low",
        "summary": "",
        "key_signals": [],
        "available": False,
        "reason": reason,
    }
