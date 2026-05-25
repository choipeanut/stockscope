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


def _get_stmt_fundamentals(ticker: str) -> dict:
    """재무제표(income_stmt/balance_sheet/cashflow)로 펀더멘털 계산.
    US 주식과 .KS 한국 주식 모두 동일 구조 사용."""
    import math
    import yfinance as yf

    result: dict = {
        "revenue_growth": None, "eps_growth": None,
        "op_margin": None, "roe": None, "roa": None,
        "debt_ratio": None, "interest_coverage": None,
        "operating_cf": None, "fcf": None,
        "dividend_payout": None, "buyback": None,
        "source": "yfinance_stmt", "available": False,
    }

    def safe(v):
        if v is None:
            return None
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except Exception:
            return None

    def row(df, *names):
        if df is None or df.empty:
            return None
        for n in names:
            if n in df.index:
                v = df.loc[n].iloc[0]
                return safe(v)
        return None

    def row_prev(df, *names):
        if df is None or df.empty or df.shape[1] < 2:
            return None
        for n in names:
            if n in df.index:
                v = df.loc[n].iloc[1]
                return safe(v)
        return None

    try:
        tk = yf.Ticker(ticker)
        income = tk.income_stmt
        balance = tk.balance_sheet
        cashflow = tk.cashflow

        revenue = row(income, "Total Revenue", "Operating Revenue")
        prev_revenue = row_prev(income, "Total Revenue", "Operating Revenue")
        op_income = row(income, "Operating Income", "Total Operating Income As Reported")
        net_income = row(income, "Net Income", "Net Income Common Stockholders",
                         "Net Income From Continuing Operation Net Minority Interest")
        total_equity = row(balance, "Stockholders Equity", "Common Stock Equity",
                           "Total Equity Gross Minority Interest")
        total_assets = row(balance, "Total Assets")
        total_debt = row(balance, "Total Debt", "Total Liabilities Net Minority Interest")
        ocf = row(cashflow, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
        capex = row(cashflow, "Capital Expenditure", "Purchase Of PPE")

        if revenue and prev_revenue and prev_revenue != 0:
            result["revenue_growth"] = round((revenue - prev_revenue) / abs(prev_revenue) * 100, 1)

        if op_income and revenue and revenue != 0:
            result["op_margin"] = round(op_income / revenue * 100, 1)

        if net_income and total_equity and total_equity != 0:
            result["roe"] = round(net_income / total_equity * 100, 1)

        if net_income and total_assets and total_assets != 0:
            result["roa"] = round(net_income / total_assets * 100, 1)

        if total_debt and total_equity and total_equity != 0:
            result["debt_ratio"] = round(total_debt / total_equity * 100, 1)

        if ocf is not None:
            result["operating_cf"] = ocf
            if capex is not None:
                result["fcf"] = ocf + capex  # capex는 음수로 기록됨

        result["available"] = any(
            result[k] is not None
            for k in ["revenue_growth", "op_margin", "roe", "roa"]
        )

    except Exception as e:
        result["available"] = False
        result["error"] = str(e)

    return result


def _get_us_fundamentals(ticker: str) -> dict:
    return _get_stmt_fundamentals(ticker)


def get_fundamentals(ticker: str, market: str) -> dict:
    key = f"fundamentals:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    if market == "KOSDAQ":
        # DART API 있으면 사용, 없으면 yfinance .KS 폴백
        dart_key = __import__("os").environ.get("DART_API_KEY")
        if dart_key:
            data = _get_kr_fundamentals(ticker)
            if not data.get("available"):
                data = _get_stmt_fundamentals(ticker + ".KS")
        else:
            data = _get_stmt_fundamentals(ticker + ".KS")
    else:
        data = _get_stmt_fundamentals(ticker)

    data["as_of"] = datetime.now(timezone.utc).isoformat()
    if data.get("available"):
        cache.set(key, data, _TTL)
    return data
