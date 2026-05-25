"""Tests for /macro endpoint and macro collector (T25)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app)


def test_macro_endpoint_returns_200(client):
    resp = client.get("/macro")
    assert resp.status_code == 200


def test_macro_response_has_required_keys(client):
    data = client.get("/macro").json()
    required = {"as_of", "regime", "sector_hints", "fred_available", "ecos_available", "indicators"}
    assert required.issubset(data.keys())


def test_macro_regime_is_valid_string(client):
    data = client.get("/macro").json()
    valid = {"확장", "회복", "둔화", "침체"}
    assert data["regime"] in valid


def test_macro_sector_hints_is_list(client):
    data = client.get("/macro").json()
    assert isinstance(data["sector_hints"], list)


def test_macro_indicators_structure(client):
    data = client.get("/macro").json()
    ind = data["indicators"]
    expected_keys = {
        "fed_rate", "us_10y", "yield_curve", "bok_rate",
        "usdkrw", "dxy", "us_cpi", "kr_cpi",
        "vix", "us_pmi", "sp500_60d", "nasdaq_60d", "sox_60d",
        "oil", "copper",
    }
    assert expected_keys.issubset(ind.keys())


def test_macro_vix_is_number_or_none(client):
    data = client.get("/macro").json()
    vix = data["indicators"]["vix"]
    assert vix is None or isinstance(vix, (int, float))


def test_macro_no_nan_in_indicators(client):
    import math
    data = client.get("/macro").json()
    for k, v in data["indicators"].items():
        if v is not None:
            assert not math.isnan(v), f"NaN in {k}"


def test_macro_graceful_without_keys(monkeypatch, client):
    """Should still return 200 even if keys are unset."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    resp = client.get("/macro")
    assert resp.status_code == 200
    data = resp.json()
    assert "regime" in data
