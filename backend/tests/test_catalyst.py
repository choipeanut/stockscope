"""Catalyst scoring tests — earnings surprise math + combine logic, no network.

Claude (`catalyst_read`) is stubbed; we only lock in the deterministic parts:
the point-in-time YoY surprise score and the weighted blend around 50.
"""
from __future__ import annotations

import pandas as pd

from app.services import catalyst as cat


def _hist(revenue, prev_revenue, op_income, prev_op_income):
    """Minimal one-row DART-history frame (already-public latest report)."""
    return pd.DataFrame([{
        "available_from": "2025-03-31", "fiscal_year": 2024,
        "revenue": revenue, "op_income": op_income, "net_income": None,
        "equity": None, "assets": None, "debt": None,
        "prev_revenue": prev_revenue, "prev_op_income": prev_op_income,
    }])


def test_surprise_neutral_when_no_history():
    out = cat.earnings_surprise(None)
    assert out["score"] == 50.0 and out["available"] is False
    out2 = cat.earnings_surprise(pd.DataFrame())
    assert out2["score"] == 50.0 and out2["available"] is False


def test_surprise_positive_growth_scores_above_50():
    # +30% revenue, +50% op income → clearly bullish
    out = cat.earnings_surprise(_hist(1300, 1000, 150, 100))
    assert out["available"] is True
    assert out["score"] > 50.0
    assert round(out["revenue_yoy"], 3) == 0.300
    assert round(out["op_yoy"], 3) == 0.500


def test_surprise_negative_growth_scores_below_50():
    out = cat.earnings_surprise(_hist(800, 1000, 50, 100))
    assert out["score"] < 50.0


def test_surprise_saturates_and_stays_in_bounds():
    # absurd 10x growth must not exceed 100
    out = cat.earnings_surprise(_hist(10000, 1000, 5000, 100))
    assert 50.0 < out["score"] <= 100.0


def test_combined_blends_surprise_and_catalyst(monkeypatch):
    # stub Claude: strong bullish catalyst (score 90)
    monkeypatch.setattr(cat, "catalyst_read", lambda *a, **k: {
        "direction": "bullish", "materiality": "high",
        "catalyst_type": "guidance_up", "score": 90,
        "thesis": "가이던스 상향", "available": True,
    })
    res = cat.catalyst_score(
        "005930", "KOSDAQ",
        dart_history=_hist(1300, 1000, 150, 100),
        disclosures=[{"title": "영업(잠정)실적 가이던스 상향", "published": "20250410"}],
    )
    # both parts bullish → combined well above neutral, thesis carries the read
    assert res["score"] > 60.0
    assert "가이던스" in res["thesis"]
    assert res["surprise"]["available"] and res["catalyst"]["available"]


def test_combined_neutral_when_nothing_fires(monkeypatch):
    monkeypatch.setattr(cat, "catalyst_read", lambda *a, **k: {
        "direction": "neutral", "materiality": "low", "catalyst_type": "none",
        "score": 50, "thesis": "", "available": False,
    })
    res = cat.catalyst_score("AAPL", "NASDAQ", dart_history=None, disclosures=[])
    assert res["score"] == 50.0
    assert res["thesis"] == "뚜렷한 촉매 없음"


# ── reflection loop: lessons injection + post-mortem ─────────────────────────

import sys
import types


def _fake_anthropic(monkeypatch, response_text: str, capture: dict):
    """Inject a fake `anthropic` module that captures the prompt sent to Claude."""
    mod = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **kw):
            capture["system"] = kw.get("system")
            capture["prompt"] = kw["messages"][0]["content"]
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text=response_text)])

    class _Client:
        def __init__(self, **kw):
            self.messages = _Messages()

    mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)


def test_format_lessons_empty():
    assert cat._format_lessons(None) is None
    assert cat._format_lessons(["  ", ""]) is None


def test_lessons_injected_into_catalyst_read_prompt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    cap: dict = {}
    _fake_anthropic(monkeypatch,
        '{"direction":"neutral","materiality":"low","catalyst_type":"none","score":50,"thesis":""}',
        cap)
    cat.catalyst_read(
        "005930", "KOSPI",
        [{"title": "단일판매·공급계약체결", "published": "20250101"}],
        lessons=["수주는 계약금액/매출대비 비중 확인", "제목만으로 과대평가 금지"],
    )
    assert "배운 교훈" in cap["prompt"]
    assert "계약금액" in cap["prompt"]


def test_no_lessons_keeps_prompt_clean(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    cap: dict = {}
    _fake_anthropic(monkeypatch,
        '{"direction":"neutral","materiality":"low","catalyst_type":"none","score":50,"thesis":""}',
        cap)
    cat.catalyst_read("005930", "KOSPI", [{"title": "x", "published": "1"}])
    assert "배운 교훈" not in cap["prompt"]


def test_postmortem_parses_analysis_and_lessons(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    cap: dict = {}
    resp = (
        '{"postmortem":"가설 방향은 맞았으나 수주 규모를 과대평가했다.",'
        '"lessons":['
        '{"scope":"global","catalyst_type":"contract_win","lesson":"수주는 매출대비 비중 확인"},'
        '{"scope":"ticker","catalyst_type":null,"lesson":"이 종목은 공시 반응이 약함"}'
        ']}'
    )
    _fake_anthropic(monkeypatch, resp, cap)
    pred = {
        "ticker": "005930", "market": "KOSPI", "name": "삼성전자",
        "thesis": "대형 수주", "score": 80, "horizon_days": 21,
        "created_at": "2025-01-01", "scored_at": "2025-02-01",
        "stock_return": 0.05, "bench_return": 0.02, "excess_return": 0.03, "hit": 1,
        "features": '{"catalyst":{"catalyst_type":"contract_win","direction":"bullish"}}',
    }
    res = cat.catalyst_postmortem(pred, window_disclosures=[
        {"title": "공급계약 정정", "published": "20250115"}])
    assert res["available"] is True
    assert "과대평가" in res["postmortem"]
    assert len(res["lessons"]) == 2
    assert res["lessons"][0]["scope"] == "global"
    assert res["lessons"][1]["scope"] == "ticker"
    # the actual outcome must reach the prompt
    assert "초과수익" in cap["prompt"] and "적중" in cap["prompt"]
    assert "공급계약 정정" in cap["prompt"]


def test_postmortem_no_key_degrades(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = cat.catalyst_postmortem({"ticker": "AAPL", "market": "NASDAQ"}, [])
    assert res["available"] is False and res["lessons"] == []
