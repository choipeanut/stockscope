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
