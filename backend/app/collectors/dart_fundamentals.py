"""Point-in-time DART fundamental history for Korean tickers.

Unlike `fundamentals.get_fundamentals` (which returns a single *latest* snapshot
and would leak the future in a backtest), this builds a TIME-INDEXED history:
one row per fiscal year, each stamped with `available_from` — the earliest date
the market could have known those numbers.

Korean issuers must file the annual business report (사업보고서) within 90 days of
fiscal year-end. We therefore set:

    available_from = fiscal_year_end (Dec 31) + 90 days  ≈  Mar 31 next year

which is conservative (never earlier than the real filing), so a point-in-time
slice `available_from <= as_of` can NEVER use a report that wasn't public yet.

A single DART annual statement carries the current term (`thstrm_amount`) AND the
prior term (`frmtrm_amount`), so year-over-year growth needs only one call per
fiscal year.

Everything degrades gracefully: no key / no network / parse failure → empty
DataFrame, and the caller simply trains a price-only model.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.collectors import cache

logger = logging.getLogger(__name__)

_TTL = 7 * 86400  # fundamentals change slowly; cache a week

# Columns of the history DataFrame returned to callers.
HISTORY_COLS = [
    "available_from",   # date the numbers became public (point-in-time gate)
    "fiscal_year",
    "revenue", "op_income", "net_income", "equity", "assets", "debt",
    "prev_revenue", "prev_op_income",
]

# DART account-name substrings (consolidated statements use these labels).
_ACCOUNTS = {
    "revenue": "매출액",
    "op_income": "영업이익",
    "net_income": "당기순이익",
    "equity": "자본총계",
    "assets": "자산총계",
    "debt": "부채총계",
}


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    import math
    return None if (math.isnan(f) or math.isinf(f)) else f


def _row_value(fs: pd.DataFrame, account_nm: str, col: str) -> float | None:
    """First matching account row's amount in `col` (thstrm_amount / frmtrm_amount)."""
    rows = fs[fs["account_nm"].str.contains(account_nm, na=False)]
    if rows.empty:
        return None
    return _to_float(rows.iloc[0].get(col))


def _available_from(fiscal_year: int) -> date:
    return date(fiscal_year, 12, 31) + timedelta(days=90)


def _build_history_from_reader(dr, corp_code: str, years: int) -> list[dict]:
    """Fetch `years` annual reports and flatten to history rows. Network-bound."""
    this_year = datetime.now(timezone.utc).year
    rows: list[dict] = []
    # Fiscal years that could plausibly be filed by now (skip current year until
    # its report would be public).
    for fy in range(this_year - 1, this_year - 1 - years, -1):
        try:
            fs = dr.finstate_all(corp_code, fy, reprt_code="11011")
        except Exception:
            fs = None
        if fs is None or fs.empty or "account_nm" not in fs.columns:
            continue
        rec = {"fiscal_year": fy, "available_from": _available_from(fy)}
        for key, account in _ACCOUNTS.items():
            rec[key] = _row_value(fs, account, "thstrm_amount")
        rec["prev_revenue"] = _row_value(fs, _ACCOUNTS["revenue"], "frmtrm_amount")
        rec["prev_op_income"] = _row_value(fs, _ACCOUNTS["op_income"], "frmtrm_amount")
        # require at least revenue to be a usable row
        if rec.get("revenue") is not None:
            rows.append(rec)
    return rows


def get_kr_fundamental_history(ticker: str, years: int = 6) -> pd.DataFrame:
    """Time-indexed annual fundamentals for a KR ticker (point-in-time safe).

    Returns a DataFrame with `HISTORY_COLS`, sorted by `available_from`.
    Empty DataFrame when DART is unavailable or nothing parses.
    """
    cache_key = f"dart_hist:{ticker}:{years}"
    cached = cache.get(cache_key)
    if cached:
        return pd.DataFrame(cached[0], columns=HISTORY_COLS)

    dart_key = os.environ.get("DART_API_KEY")
    if not dart_key:
        return pd.DataFrame(columns=HISTORY_COLS)

    rows: list[dict] = []
    try:
        import OpenDartReader
        dr = OpenDartReader.OpenDartReader(dart_key)
        codes = dr.corp_codes
        match = codes[codes["stock_code"] == ticker]
        if match is None or match.empty:
            return pd.DataFrame(columns=HISTORY_COLS)
        corp_code = match.iloc[0]["corp_code"]
        rows = _build_history_from_reader(dr, corp_code, years)
    except Exception as e:
        logger.debug("dart history failed %s: %s", ticker, e)
        return pd.DataFrame(columns=HISTORY_COLS)

    df = pd.DataFrame(rows, columns=HISTORY_COLS)
    if not df.empty:
        df["available_from"] = pd.to_datetime(df["available_from"]).dt.date
        df = df.sort_values("available_from").reset_index(drop=True)
        # cache as list-of-dicts (JSON-friendly); dates become strings, that's ok
        cache.set(cache_key, df.to_dict("records"), _TTL)
    return df
