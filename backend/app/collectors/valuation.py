"""Valuation data collector — PER/PBR/PSR 등.

NASDAQ: yfinance 재무제표(income_stmt/balance_sheet)로 직접 계산
         → .info 대신 별도 엔드포인트 사용 (Render rate limit 우회)
KOSDAQ:  pykrx
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

from app.collectors import cache

_TTL = 3600  # 1시간


def _safe(val: Any, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _row(df, *names):
    """재무제표 DataFrame에서 첫 번째 매칭 행의 최신 값 반환."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            v = df.loc[name].iloc[0]
            return _safe(v)
    return None


def _get_fdr_shares(ticker: str) -> float | None:
    """FinanceDataReader KRX 상장 정보에서 주식 수 조회."""
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing("KRX")
        row = df[df["Code"] == ticker]
        if row.empty:
            return None
        v = row.iloc[0].get("Stocks")
        return float(v) if v and float(v) > 0 else None
    except Exception:
        return None


def _get_kr_valuation(ticker: str) -> dict:
    """한국 주식 밸류에이션: pykrx 우선, 실패 시 yfinance .KS + FDR 폴백."""
    # 1) pykrx 시도
    pykrx_result = _try_pykrx_valuation(ticker)
    if pykrx_result.get("available"):
        return pykrx_result

    # 2) yfinance .KS 폴백 (재무제표 기반 계산)
    ks_ticker = ticker + ".KS"
    result = _get_us_valuation(ks_ticker)
    result["source"] = "yfinance_ks"

    # 3) yfinance가 주식수를 못 가져왔을 경우 FDR에서 보완
    if result.get("per") is None and result.get("pbr") is None:
        fdr_shares = _get_fdr_shares(ticker)
        if fdr_shares:
            # yfinance 재무제표에서 순이익·자기자본 재시도 (shares 주입)
            import yfinance as yf
            tk = yf.Ticker(ks_ticker)
            try:
                income = tk.income_stmt
                balance = tk.balance_sheet
                price = None
                try:
                    price = float(tk.fast_info.last_price)
                except Exception:
                    hist = tk.history(period="5d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])

                net_income = _row(income,
                    "Net Income", "Net Income Common Stockholders",
                    "Net Income From Continuing Operation Net Minority Interest")
                total_equity = _row(balance,
                    "Stockholders Equity", "Total Equity Gross Minority Interest",
                    "Common Stock Equity")

                if price and net_income and fdr_shares > 0:
                    eps = net_income / fdr_shares
                    result["eps"] = round(eps, 4)
                    if eps > 0:
                        result["per"] = round(price / eps, 2)
                    result["available"] = True

                if price and total_equity and fdr_shares > 0:
                    bps = total_equity / fdr_shares
                    result["bps"] = round(bps, 2)
                    if bps > 0:
                        result["pbr"] = round(price / bps, 2)
                    result["available"] = True

                result["source"] = "yfinance_ks+fdr"
            except Exception:
                pass

    return result


def _try_pykrx_valuation(ticker: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "eps": None, "bps": None, "roe": None,
        "source": "pykrx", "available": True,
    }
    try:
        from pykrx import stock as pykrx_stock
        df = pykrx_stock.get_market_fundamental(today, today, ticker)
        if df is None or df.empty:
            result["available"] = False
            return result

        row = df.iloc[-1]
        result["per"] = _safe(row.get("PER") or row.get("per"))
        result["pbr"] = _safe(row.get("PBR") or row.get("pbr"))
        result["eps"] = _safe(row.get("EPS") or row.get("eps"))
        result["bps"] = _safe(row.get("BPS") or row.get("bps"))
        result["dividend_yield"] = _safe(row.get("DIV") or row.get("div"))

        # 5년 PER 분위
        try:
            start_5y = (datetime.now(timezone.utc).replace(
                year=datetime.now(timezone.utc).year - 5)
            ).strftime("%Y%m%d")
            df5 = pykrx_stock.get_market_fundamental(start_5y, today, ticker)
            if df5 is not None and not df5.empty and result["per"] is not None:
                per_col = "PER" if "PER" in df5.columns else "per"
                per_s = df5[per_col].replace(0, None).dropna()
                if len(per_s) > 10:
                    result["per_5y_pct"] = round(
                        (per_s < result["per"]).mean() * 100, 1
                    )
        except Exception:
            pass

    except Exception:
        result["available"] = False

    if result["per"] is None and result["pbr"] is None:
        result["available"] = False
    return result


def _get_us_valuation(ticker: str) -> dict:
    import yfinance as yf

    result: dict = {
        "per": None, "pbr": None, "dividend_yield": None,
        "psr": None, "ev_ebitda": None, "per_5y_pct": None,
        "eps": None, "bps": None, "market_cap": None,
        "forward_pe": None, "peg_ratio": None,
        "roe": None, "revenue": None,
        "source": "yfinance", "available": False,
    }

    tk = yf.Ticker(ticker)

    # ── 1) 현재 주가 + 기본 지표 (fast_info는 항상 됨) ───────────
    price = None
    shares_fi = None
    market_cap_fi = None
    for attempt in range(3):
        try:
            fi = tk.fast_info
            price = _safe(fi.last_price)
            shares_fi = _safe(fi.shares)
            market_cap_fi = _safe(fi.market_cap)
            break
        except Exception:
            time.sleep(2)

    # fast_info 실패 시 history fallback
    if price is None:
        for attempt in range(3):
            try:
                hist = tk.history(period="5d", auto_adjust=True)
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    break
            except Exception:
                time.sleep(2)

    if price is None:
        return result

    # ── 2) 재무제표 (income_stmt / balance_sheet / cashflow) ──────
    income, balance, cashflow = None, None, None
    for attempt in range(3):
        try:
            income = tk.income_stmt
            balance = tk.balance_sheet
            cashflow = tk.cashflow
            break
        except Exception:
            time.sleep(3)

    # ── 3) 핵심 지표 계산 ─────────────────────────────────────────
    net_income = _row(income,
        "Net Income", "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest")
    total_equity = _row(balance,
        "Stockholders Equity", "Total Equity Gross Minority Interest",
        "Common Stock Equity")
    shares = _row(balance,
        "Ordinary Shares Number", "Share Issued",
        "Common Stock")
    revenue = _row(income,
        "Total Revenue", "Operating Revenue")
    prev_revenue = None
    if income is not None and not income.empty and income.shape[1] >= 2:
        for name in ["Total Revenue", "Operating Revenue"]:
            if name in income.index:
                prev_revenue = _safe(income.loc[name].iloc[1])
                break
    ocf = _row(cashflow,
        "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = _row(cashflow,
        "Capital Expenditure", "Purchase Of Ppe")

    # 시가총액 (fast_info 우선)
    shares = shares or shares_fi
    market_cap = market_cap_fi
    if market_cap is None and shares and shares > 0 and price:
        market_cap = price * shares
    result["market_cap"] = market_cap

    # EPS / PER
    if net_income and shares and shares > 0:
        eps = net_income / shares
        result["eps"] = round(eps, 4)
        if eps > 0:
            result["per"] = round(price / eps, 2)

    # BPS / PBR
    if total_equity and shares and shares > 0:
        bps = total_equity / shares
        result["bps"] = round(bps, 2)
        if bps > 0:
            result["pbr"] = round(price / bps, 2)

    # PSR
    if revenue and market_cap and revenue > 0:
        result["psr"] = round(market_cap / revenue, 2)

    # ROE / Revenue growth
    if net_income and total_equity and total_equity > 0:
        result["roe"] = round(net_income / total_equity * 100, 1)

    if revenue:
        result["revenue"] = revenue
        if prev_revenue and prev_revenue > 0:
            result["revenue_growth"] = round(
                (revenue - prev_revenue) / abs(prev_revenue) * 100, 1
            )

    # FCF
    if ocf is not None and capex is not None:
        result["fcf"] = ocf + capex  # capex는 음수로 기록됨

    # ── 4) info 보완 (성공하면 추가 지표) ────────────────────────
    for attempt in range(2):
        try:
            info = tk.info
            if info:
                result["forward_pe"] = _safe(info.get("forwardPE"))
                result["peg_ratio"] = _safe(info.get("pegRatio"))
                result["ev_ebitda"] = _safe(info.get("enterpriseToEbitda"))
                # trailingAnnualDividendYield이 정확함 (dividendYield는 버그 있음)
                dy = _safe(
                    info.get("trailingAnnualDividendYield")
                    or info.get("dividendYield")
                )
                if dy and dy < 0.5:  # 50% 이상은 데이터 오류
                    result["dividend_yield"] = round(dy * 100, 2)
                result["per"] = result["per"] or _safe(
                    info.get("trailingPE") or info.get("forwardPE")
                )
                result["pbr"] = result["pbr"] or _safe(info.get("priceToBook"))
            break
        except Exception:
            break

    result["available"] = (
        result["per"] is not None or result["pbr"] is not None
    )
    return result


def get_valuation(ticker: str, market: str) -> dict:
    key = f"valuation:{market}:{ticker}"
    cached = cache.get(key)
    if cached:
        return cached[0]

    data = _get_kr_valuation(ticker) if market == "KOSDAQ" else _get_us_valuation(ticker)
    data["as_of"] = datetime.now(timezone.utc).isoformat()
    if data.get("available"):
        cache.set(key, data, _TTL)
    return data
