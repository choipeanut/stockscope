"""전체 시장 환경 감성 분석 — Claude Haiku 사용.

글로벌 거시 뉴스를 분석하여 시장 전반의 투자 환경 점수(0-100)를 반환한다.
  50 = 중립 / >50 = 강세 환경 / <50 = 약세 환경

결과는 1시간 인메모리 캐시로 저장 (market-level, ticker 무관).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_CACHE_TTL = 3600  # 1시간

_SYSTEM = """당신은 글로벌 금융시장 환경 분석 전문가입니다.
제공된 글로벌 거시 뉴스들을 종합 분석하여 현재 주식시장의 전반적인 투자 환경을 평가하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "market_score": 0~100 사이의 정수,
  "market_trend": "bullish" | "bearish" | "neutral",
  "confidence": "high" | "medium" | "low",
  "summary": "한 줄 요약 (한국어, 60자 이내)",
  "key_themes": ["테마1", "테마2", "테마3"]
}

market_score 기준:
- 80-100: 매우 강세 (금리인하 + 경기호조 + 무역완화 + 시장안정)
- 65-79: 강세 (대부분 긍정적 신호)
- 50-64: 약한 강세 또는 중립
- 36-49: 약한 약세 또는 불확실
- 20-35: 약세 (금리인상/전쟁/경기둔화 등 부정적 신호 우세)
- 0-19: 매우 약세 (복합 위기 상황)

분석 항목:
- 중앙은행 정책 (금리, 양적완화/긴축)
- 지정학적 리스크 (전쟁, 제재, 무역분쟁)
- 경제 지표 (GDP, 실업률, CPI, PMI)
- 시장 심리 (VIX, 투자자 심리, 자금 흐름)
- 기업 실적 전반 트렌드
- 글로벌 무역 및 공급망

중립적 기준점(50)에서 각 요소별 영향을 종합하여 최종 점수를 산출하세요."""

_cache: dict[str, Any] = {}


def _get_cached() -> dict | None:
    entry = _cache.get("market_sentiment")
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cache(data: dict) -> None:
    _cache["market_sentiment"] = {"data": data, "ts": time.time()}


def analyze_market_sentiment(news_items: list[dict]) -> dict:
    """
    글로벌 거시 뉴스로 시장 전반 감성 분석.

    Returns:
        {
          market_score: int (0-100),
          market_trend: str ("bullish" | "bearish" | "neutral"),
          confidence: str,
          summary: str (Korean),
          key_themes: list[str] (Korean, max 3),
          available: bool,
        }
    """
    cached = _get_cached()
    if cached:
        return cached

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _unavailable("ANTHROPIC_API_KEY not set")

    if not news_items:
        return _unavailable("no global macro news available")

    lines = ["=== 글로벌 거시 환경 뉴스 ===", ""]
    for item in news_items[:20]:
        source = item.get("source", "")
        title = item.get("title", "")
        published = (item.get("published") or "")[:10]
        lines.append(f"- [{published}] [{source}] {title}")

    prompt = "\n".join(lines)

    try:
        from app.services.claude_json import call_claude_json
        result = call_claude_json(api_key, _MODEL, _SYSTEM, prompt, max_tokens=512)
        result["available"] = True
        _set_cache(result)
        return result

    except Exception as e:
        logger.warning("market sentiment analysis failed: %s", e)
        return _unavailable(str(e))


def _unavailable(reason: str) -> dict:
    return {
        "market_score": 50,
        "market_trend": "neutral",
        "confidence": "low",
        "summary": "",
        "key_themes": [],
        "available": False,
        "reason": reason,
    }
