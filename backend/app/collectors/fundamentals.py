"""Fundamental data collector — growth/profitability/stability/cashflow/payout."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.collectors import cache

_TTL = 86400


def _safe(val: Any) -> float | None:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _get_kr_fundamentals(ticker: str) -> dict:
    dart_key = os.environ.get("DART_API_KEY")
    result: dict = {
        "revenue_growth": None, "eps_growth": None,
        "op_margin": None, "roe": None, "roa": None,
        "debt_ratio": None, "interest_coverage": None,
        "operating_cf": None, "fcf": None,
        "dividend_payout": None, "buyback": None,
        "source": "OpenDartReader", "available": bool(dart_key),
        "key_required": None if dart_key else "DART_API_KEY",
    }
    if not dart_key:
        return result
    try:
        import OpenDartReader as dart
        dr = dart.OpenDartReader(dart_key)

        # Find corp code
        corp = dr.find_corp_code(ticker)
        if corp is None or corp.empty:
            result["available"] = False
            return result
        corp_code = corp.iloc[0]["corp_code"]

        year = datetime.now(timezone.utc).year
        # Try current year first, fall back to prior year
        for y in [year - 1, year - 2]:
            try:
                fs = dr.finstate_all(corp_code, y, reprt_code="11011")
                if fs is not None and not fs.empty:
                    break
            except Exception:
                fs = None

        if fs is None or fs.empty:
            result["available"] = False
            return result

        def get_val(account_nm: str) -> float | None:
            rows = fs[fs["account_nm"].str.contains(account_nm, na=False)]
            if rows.empty:
                return None
            v = rows.iloc[0].get("thstrm_amount") or rows.iloc[0].get("당기")
            return _safe(str(v).replace(",", "") if v else None)

        revenue = get_val("매출액")
        prev_revenue = get_val("전기매출") or None
        if revenue and prev_revenue and prev_revenue != 0:
            result["revenue_growth"] = (revenue - prev_revenue) / abs(prev_revenue) * 100

        op_income = get_val("영업이익")
        if op_income and revenue and revenue != 0:
            result["op_margin"] = op_income / revenue * 100

        total_equity = get_val("자본총계")
        net_income = get_val("당기순이익")
        total_assets = get_val("자산총계")
        total_debt = get_val("부채총계")

        if net_income and total_equity and total_equity != 0:
            result["roe"] = net_income / total_equity * 100
        if net_income and total_assets and total_assets != 0:
            result["roa"] = net_income / total_assets * 100
        if total_debt and total_equity and total_equity != 0:
            result["debt_ratio"] = total_debt / total_equity * 100

        ocf = get_val("영업활동")
        capex = get_val("유형자산") or 0
        if ocf is not None:
            result["operating_cf"] = ocf
            result["fcf"] = ocf - abs(capex) if capex else ocf

        dps = get_val("배당금")
        if dps and net_income and net_income > 0:
            result["dividend_payout"] = dps / net_income * 100

    except Exception as e:
        result["available"] = False
        result["error"] = str(e)
    return result


def _get_us_fundamentals(ticker: str) -> dict:
    result: dict = {
        "revenue_growth": None, "eps_growth": None,
        "op_margin": None, "roe": None, "roa": None,
        "debt_ratio": None, "interest_coverage": None,
        "operating_cf": None, "fcf": None,
        "dividend_payout": None, "buyback": None,
        "source": "yfinance", "available": True,
    }
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        info = tk.info

        result["op_margin"] = _safe(info.get("operatingMargins", 0) * 100
                                    if info.get("operatingMargins") else None)
        result["roe"] = _safe(info.get("returnOnEquity", 0) * 100
                              if info.get("returnOnEquity") else None)
        result["roa"] = _safe(info.get("returnOnAssets", 0) * 100
                              if info.get("returnOnAssets") else None)

        de = _safe(info.get("debtToEquity"))
        result["debt_ratio"] = de  # already a ratio

        # Revenue growth from financials
        try:
            fin = tk.financials
            if fin is not None and not fin.empty and fin.shape[1] >= 2:
                rev_row = fin.loc["Total Revenue"] if "Total Revenue" in fin.index else None
                if rev_row is not None:
                    r0, r1 = float(rev_row.iloc[0]), float(rev_row.iloc[1])
                    if r1 and r1 != 0:
                        result["revenue_growth"] = (r0 - r1) / abs(r1) * 100
        except Exception:
            pass

        # Cash flow
        try:
            cf = tk.cashflow
            if cf is not None and not cf.empty:
                ocf_row = (cf.loc["Operating Cash Flow"]
                           if "Operating Cash Flow" in cf.index else None)
                capex_row = (cf.loc["Capital Expenditure"]
                             if "Capital Expenditure" in cf.index else None)
                if ocf_row is not None:
                    result["operating_cf"] = float(ocf_row.iloc[0])
                if ocf_row is not None and capex_row is not None:
                    result["fcf"] = float(ocf_row.iloc[0]) + float(capex_row.iloc[0])
        except Exception:
            pass

        pr = _safe(info.get("payoutRatio"))
        result["dividend_payout"] = pr * 100 if pr else None

    except Exception as e:
        result["available"] = False
        result["error"] = str(e)
    return result


def get_fundamentals(ticker: str, market: str) -> dict:
    key = f"fundamentals:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    data = _get_kr_fundamentals(ticker) if market == "KOSDAQ" else _get_us_fundamentals(ticker)
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    cache.set(key, data, _TTL)
    return data
