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

import contextlib
import io
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.collectors import cache


@contextlib.contextmanager
def quiet_stdout():
    """Swallow library-level print() noise (OpenDartReader echoes every query
    and DART 'no data' responses to stdout, flooding the logs)."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield

logger = logging.getLogger(__name__)

_TTL = 7 * 86400  # fundamentals change slowly; cache a week

# Columns of the history DataFrame returned to callers.
HISTORY_COLS = [
    "available_from",   # date the numbers became public (point-in-time gate)
    "fiscal_year",
    "revenue", "op_income", "net_income", "equity", "assets", "debt",
    "prev_revenue", "prev_op_income",
]

# Robust account matching. EXACT standardized XBRL `account_id` codes first
# (stable across companies, avoids "Assets" also matching "CurrentAssets"), then
# exact Korean `account_nm`, then a loose name contains as last resort.
# Each metric: (exact account_id candidates, exact/loose account_nm candidates).
_METRICS: dict[str, tuple[list[str], list[str]]] = {
    "revenue": (
        ["ifrs-full_Revenue", "ifrs_Revenue"],
        ["매출액", "영업수익", "수익(매출액)"],
    ),
    "op_income": (
        ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
        ["영업이익", "영업이익(손실)"],
    ),
    "net_income": (
        ["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"],
        ["당기순이익", "당기순이익(손실)"],
    ),
    "equity": (
        ["ifrs-full_Equity", "ifrs_Equity"],
        ["자본총계"],
    ),
    "assets": (
        ["ifrs-full_Assets", "ifrs_Assets"],
        ["자산총계"],
    ),
    "debt": (
        ["ifrs-full_Liabilities", "ifrs_Liabilities"],
        ["부채총계"],
    ),
}


def make_reader(dart_key: str):
    """Construct an OpenDartReader, robust to package layout.

    Depending on the installed version, `import OpenDartReader` binds either the
    class itself (callable directly) or a module exposing `.OpenDartReader`.
    """
    import OpenDartReader
    cls = getattr(OpenDartReader, "OpenDartReader", OpenDartReader)
    return cls(dart_key)


# A single shared reader per process. OpenDartReader loads the ENTIRE Korean
# corp_codes table (tens of thousands of rows) on construction; building one
# per ticker — especially across parallel workers — stacks several copies of
# that table in memory and OOMs a 512 MB box. We build it once, guarded by a
# lock, and reuse it for every ticker.
import threading as _threading

_reader_lock = _threading.Lock()
_shared_reader = None


def get_shared_reader(dart_key: str):
    """Return a process-wide singleton OpenDartReader (one corp_codes table)."""
    global _shared_reader
    if _shared_reader is None:
        with _reader_lock:
            if _shared_reader is None:
                _shared_reader = make_reader(dart_key)
    return _shared_reader


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "–"):
        return None
    # accounting negatives: "(1,234)" → -1234
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    import math
    return None if (math.isnan(f) or math.isinf(f)) else f


def _prefer_consolidated(fs: pd.DataFrame) -> pd.DataFrame:
    """Use consolidated (CFS) statements when present, else separate (OFS)."""
    if "fs_div" not in fs.columns:
        return fs
    cfs = fs[fs["fs_div"] == "CFS"]
    return cfs if not cfs.empty else fs


def _first_value(rows: pd.DataFrame, col: str) -> float | None:
    for _, row in rows.iterrows():
        val = _to_float(row.get(col))
        if val is not None:
            return val
    return None


def _row_value(fs: pd.DataFrame, metric: str, col: str) -> float | None:
    """Amount in `col` for the row matching `metric`, most-specific match first."""
    id_cands, nm_cands = _METRICS[metric]
    # 1) exact account_id (most reliable, no substring contamination)
    if "account_id" in fs.columns:
        v = _first_value(fs[fs["account_id"].isin(id_cands)], col)
        if v is not None:
            return v
    # 2) exact account_nm
    if "account_nm" in fs.columns:
        v = _first_value(fs[fs["account_nm"].isin(nm_cands)], col)
        if v is not None:
            return v
        # 3) loose name contains (last resort)
        pattern = "|".join(re.escape(c) for c in nm_cands)
        v = _first_value(
            fs[fs["account_nm"].str.contains(pattern, na=False, regex=True)], col
        )
        if v is not None:
            return v
    return None


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
            with quiet_stdout():
                fs = dr.finstate_all(corp_code, fy, reprt_code="11011")
        except Exception:
            fs = None
        if fs is None or fs.empty or "account_nm" not in fs.columns:
            continue
        fs = _prefer_consolidated(fs)
        rec = {"fiscal_year": fy, "available_from": _available_from(fy)}
        for metric in _METRICS:
            rec[metric] = _row_value(fs, metric, "thstrm_amount")
        rec["prev_revenue"] = _row_value(fs, "revenue", "frmtrm_amount")
        rec["prev_op_income"] = _row_value(fs, "op_income", "frmtrm_amount")
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
        dr = get_shared_reader(dart_key)  # shared singleton — one corp_codes table
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
        # Cache as JSON-safe records: dates → ISO strings (read path re-parses via
        # pd.to_datetime). Best-effort — a cache failure must never break the fetch.
        records = df.to_dict("records")
        for r in records:
            af = r.get("available_from")
            if hasattr(af, "isoformat"):
                r["available_from"] = af.isoformat()
        try:
            cache.set(cache_key, records, _TTL)
        except Exception as e:
            logger.debug("dart history cache skip %s: %s", ticker, e)
    return df
