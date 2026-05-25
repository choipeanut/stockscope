"""뉴스·공시 감성 분석 — Claude Haiku 3.5 사용."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"  # 빠르고 저렴, 한국어 우수

_SYSTEM = """당신은 금융 뉴스·공시 감성 분석 전문가입니다.
주어진 뉴스/공시 목록을 분석하여 해당 종목의 투자 점수에 미치는 영향을 평가하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "sentiment": "positive" | "negative" | "neutral",
  "score_delta": -20 ~ +20 사이의 정수,
  "confidence": "high" | "medium" | "low",
  "summary": "한 줄 요약 (한국어, 50자 이내)",
  "key_signals": ["신호1", "신호2"]  // 최대 3개, 한국어
}

score_delta 기준:
- 실적 대폭 상회, 대규모 자사주 소각, M&A 성공 → +15 ~ +20
- 실적 소폭 상회, 배당 증가, 신제품 출시 → +5 ~ +14
- 중립적 뉴스, 단순 공시 → -4 ~ +4
- 실적 소폭 하회, 소송 제기, 경영진 변경 → -5 ~ -14
- 분식회계, 상장폐지 위기, 대규모 손실 → -15 ~ -20"""


def analyze_sentiment(
    ticker: str,
    market: str,
    news_items: list[dict],
    disclosures: list[dict],
) -> dict:
    """
    뉴스·공시를 Claude로 분석하여 점수 보정값 반환.

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

    all_items = disclosures + news_items
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
        lines.append("=== 최근 뉴스 ===")
        for n in news_items[:8]:
            lines.append(f"- [{n.get('source', '')}] {n.get('title', '')}")
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
