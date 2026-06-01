"""DART fundamental parsing tests — synthetic finstate data, no network.

Locks in the account matching (exact account_id wins, no "Assets" vs
"CurrentAssets" contamination) and the full history-build path via a fake
reader, since the real DART parsing has never had coverage.
"""
from __future__ import annotations

import pandas as pd

from app.collectors import dart_fundamentals as df_mod


def _finstate(year: int) -> pd.DataFrame:
    """Minimal finstate_all-shaped frame with the contamination traps present."""
    rows = [
        # contamination traps that must NOT be picked for assets/equity
        {"sj_div": "BS", "account_id": "ifrs-full_CurrentAssets", "account_nm": "유동자산",
         "thstrm_amount": "111", "frmtrm_amount": "100"},
        {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계",
         "thstrm_amount": "1000", "frmtrm_amount": "900"},
        {"sj_div": "BS", "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계",
         "thstrm_amount": "400", "frmtrm_amount": "380"},
        {"sj_div": "BS", "account_id": "ifrs-full_EquityAttributableToOwnersOfParent",
         "account_nm": "지배기업 소유주지분", "thstrm_amount": "555", "frmtrm_amount": "500"},
        {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계",
         "thstrm_amount": "600", "frmtrm_amount": "520"},
        {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
         "thstrm_amount": "2000", "frmtrm_amount": "1600"},
        {"sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익",
         "thstrm_amount": "300", "frmtrm_amount": "200"},
        {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익",
         "thstrm_amount": "240", "frmtrm_amount": "180"},
    ]
    return pd.DataFrame(rows)


class _FakeReader:
    def __init__(self, *_):
        self.corp_codes = pd.DataFrame([
            {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
        ])

    def finstate_all(self, corp_code, year, reprt_code="11011"):
        return _finstate(year)


def test_row_value_prefers_exact_id_over_substring():
    fs = _finstate(2024)
    # must pick 자산총계 (1000), NOT 유동자산 (111)
    assert df_mod._row_value(fs, "assets", "thstrm_amount") == 1000.0
    # must pick 자본총계 (600), NOT 지배기업 소유주지분 (555)
    assert df_mod._row_value(fs, "equity", "thstrm_amount") == 600.0
    assert df_mod._row_value(fs, "revenue", "thstrm_amount") == 2000.0
    assert df_mod._row_value(fs, "op_income", "thstrm_amount") == 300.0
    assert df_mod._row_value(fs, "net_income", "thstrm_amount") == 240.0
    assert df_mod._row_value(fs, "debt", "thstrm_amount") == 400.0
    # prior-term column for YoY
    assert df_mod._row_value(fs, "revenue", "frmtrm_amount") == 1600.0


def test_build_history_from_fake_reader():
    rows = df_mod._build_history_from_reader(_FakeReader(), "00126380", years=3)
    assert len(rows) == 3
    rec = rows[0]
    assert rec["revenue"] == 2000.0 and rec["prev_revenue"] == 1600.0
    assert rec["equity"] == 600.0 and rec["assets"] == 1000.0
    assert "available_from" in rec


def test_get_history_caches_json_safe(monkeypatch):
    """Full path incl. cache.set with date → ISO string (the 500-bug regression)."""
    monkeypatch.setenv("DART_API_KEY", "dummy")
    monkeypatch.setattr(df_mod, "make_reader", lambda key: _FakeReader())
    store: dict = {}
    monkeypatch.setattr(df_mod.cache, "set",
                        lambda k, v, ttl: store.__setitem__(k, v))
    monkeypatch.setattr(df_mod.cache, "get", lambda k: None)

    hist = df_mod.get_kr_fundamental_history("005930", years=3)
    assert not hist.empty
    assert len(hist) == 3
    # cached records must be JSON-serializable (no date objects)
    import json
    cached_records = next(iter(store.values()))
    json.dumps(cached_records)  # would raise if a date slipped through
    assert all(isinstance(r["available_from"], str) for r in cached_records)
