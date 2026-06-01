"""Point-in-time backtest engine (Phase 0).

Goal: honestly answer "does our factor score predict forward returns?"
This is the foundation for any prediction model — without it, every weight
and claim is a guess.

Design principles (the 4 things that kill 90% of backtests):
  1. POINT-IN-TIME: at each rebalance date we slice each ticker's OHLCV up to
     that date and compute the score from ONLY that data. No future leakage.
  2. PRICE-ONLY FACTORS for now: momentum (and price-derived volatility) are the
     only factors with genuine historical point-in-time values. Fundamental /
     valuation snapshots are "current only" and would leak the future, so they
     are deliberately excluded from Phase 0.
  3. FORWARD RETURNS measured AFTER the decision date (no overlap with the score
     window).
  4. BASELINE COMPARISON: report the long-short spread AND an equal-weight
     buy-and-hold benchmark so we can see if the score adds anything.

Output metrics:
  - IC (Information Coefficient): Spearman rank corr between score and forward
    return at each rebalance, averaged. Realistic good values are 0.03-0.05.
  - Quantile spread: forward return of top-quantile minus bottom-quantile.
  - Long-short cumulative curve vs equal-weight benchmark.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.collectors.prices import get_ohlcv
from app.collectors.universe import get_universe
from app.scoring.momentum import compute_momentum

logger = logging.getLogger(__name__)

# Minimum trading rows needed before momentum is meaningful (MA120 + buffer).
_MIN_HISTORY_ROWS = 130

_INDEX_TICKER: dict[str, str] = {"KOSDAQ": "^KQ11", "NASDAQ": "^IXIC"}


@dataclass
class RebalancePoint:
    as_of: str                      # decision date (ISO)
    n_scored: int                   # tickers with a valid score
    ic: float | None                # rank corr(score, fwd_return) at this date
    top_return: float | None        # mean fwd return of top quantile
    bottom_return: float | None     # mean fwd return of bottom quantile
    long_short: float | None        # top - bottom
    benchmark_return: float | None  # equal-weight mean fwd return


@dataclass
class BacktestResult:
    market: str
    factor: str
    start: str
    end: str
    rebalance_days: int
    holding_days: int
    n_quantiles: int
    n_rebalances: int
    # Headline metrics
    mean_ic: float | None
    ic_hit_rate: float | None       # fraction of rebalances with IC > 0
    mean_long_short: float | None   # avg per-period top-bottom spread
    long_short_cum: float | None    # compounded long-short return
    benchmark_cum: float | None     # compounded equal-weight return
    sharpe_long_short: float | None
    points: list[RebalancePoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _momentum_score(df_slice: pd.DataFrame, index_slice: pd.DataFrame | None) -> float:
    """Point-in-time momentum score from a price slice. NaN if not computable."""
    if df_slice is None or len(df_slice) < _MIN_HISTORY_ROWS:
        return float("nan")
    try:
        res = compute_momentum(df_slice, index_slice)
        return float(res.score)
    except Exception:
        return float("nan")


_FACTORS = {
    "momentum": _momentum_score,
}


def _load_prices(
    tickers: list[dict], lookback_days: int
) -> dict[tuple[str, str], pd.DataFrame]:
    """Fetch full-history OHLCV for each ticker, indexed by (ticker, market).

    Parallelised with ThreadPoolExecutor so 40+ tickers don't take 6+ min
    serially (each pykrx-miss + FDR-fallback takes ~10 s on cold cache).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(item):
        t, m = item["ticker"], item["market"]
        try:
            df = get_ohlcv(t, m, period_days=lookback_days)
            if df is not None and not df.empty:
                df = df.copy()
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
                return (t, m), df
        except Exception as e:
            logger.debug("backtest: price fetch failed %s/%s: %s", t, m, e)
        return None

    out: dict[tuple[str, str], pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(_fetch_one, item) for item in tickers]
        for fut in as_completed(futs):
            result = fut.result()
            if result is not None:
                key, df = result
                out[key] = df
    return out


def _load_index(market: str, lookback_days: int) -> pd.DataFrame | None:
    try:
        df = get_ohlcv(_INDEX_TICKER.get(market, "^IXIC"), market, period_days=lookback_days)
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def _all_trading_dates(price_map: dict[tuple[str, str], pd.DataFrame]) -> list[date]:
    dates: set[date] = set()
    for df in price_map.values():
        dates.update(df["date"].tolist())
    return sorted(dates)


def _slice_up_to(df: pd.DataFrame, as_of) -> pd.DataFrame:
    """Rows on or before as_of (point-in-time: nothing from the future).

    Coerces the date column to pandas datetime so comparison works regardless
    of whether the cache returned dates as datetime.date, str, or epoch float.
    """
    d = pd.to_datetime(df["date"], errors="coerce")
    return df[d <= pd.to_datetime(as_of)]


def _forward_return(df: pd.DataFrame, as_of, holding_days: int) -> float:
    """Close-to-close return from the last bar <= as_of to ~holding_days later."""
    d = pd.to_datetime(df["date"], errors="coerce")
    as_of_dt = pd.to_datetime(as_of)
    past = df[d <= as_of_dt]
    future = df[d > as_of_dt]
    if past.empty or future.empty:
        return float("nan")
    entry = float(past["close"].iloc[-1])
    # take the bar closest to as_of + holding_days (by trading-row count)
    if len(future) >= holding_days:
        exit_px = float(future["close"].iloc[holding_days - 1])
    else:
        exit_px = float(future["close"].iloc[-1])
    if entry <= 0:
        return float("nan")
    return exit_px / entry - 1.0


def run_backtest(
    market: str | None = None,
    factor: str = "momentum",
    years: float = 3.0,
    rebalance_days: int = 21,     # ~monthly (trading days)
    holding_days: int = 21,       # forward window
    n_quantiles: int = 5,
) -> BacktestResult:
    """Run a point-in-time, walk-forward backtest over the universe.

    Args:
        market: "KOSDAQ" | "NASDAQ" | None (both)
        factor: which point-in-time factor to test (currently "momentum")
        years: how far back to test
        rebalance_days: trading-day gap between decisions (21 ≈ monthly)
        holding_days: forward return horizon in trading days
        n_quantiles: number of buckets (5 = quintiles)
    """
    if factor not in _FACTORS:
        raise ValueError(f"unknown factor: {factor} (have {list(_FACTORS)})")
    score_fn = _FACTORS[factor]

    lookback_days = int(years * 365) + 200  # +200 so earliest dates still have MA history
    tickers = get_universe(market)
    warnings: list[str] = []

    price_map = _load_prices(tickers, lookback_days)
    if len(price_map) < n_quantiles:
        warnings.append(f"only {len(price_map)} tickers loaded; need >= {n_quantiles}")

    # Per-market index slices for relative strength
    markets = {m for (_, m) in price_map}
    index_map = {m: _load_index(m, lookback_days) for m in markets}

    trading_dates = _all_trading_dates(price_map)
    if not trading_dates:
        return BacktestResult(
            market=market or "ALL", factor=factor, start="", end="",
            rebalance_days=rebalance_days, holding_days=holding_days,
            n_quantiles=n_quantiles, n_rebalances=0, mean_ic=None, ic_hit_rate=None,
            mean_long_short=None, long_short_cum=None, benchmark_cum=None,
            sharpe_long_short=None, warnings=["no price data loaded"],
        )

    # Decision dates: every rebalance_days, leaving room for the forward window
    # and enough history at the start.
    start_idx = _MIN_HISTORY_ROWS
    end_idx = len(trading_dates) - holding_days - 1
    decision_idxs = list(range(start_idx, max(start_idx, end_idx), rebalance_days))

    points: list[RebalancePoint] = []
    ls_returns: list[float] = []
    bench_returns: list[float] = []

    for di in decision_idxs:
        as_of = trading_dates[di]
        scores: dict[tuple[str, str], float] = {}
        fwd: dict[tuple[str, str], float] = {}

        for key, df in price_map.items():
            _, m = key
            sl = _slice_up_to(df, as_of)
            idx = index_map.get(m)
            idx_sl = _slice_up_to(idx, as_of) if idx is not None else None
            s = score_fn(sl, idx_sl)
            if np.isnan(s):
                continue
            fr = _forward_return(df, as_of, holding_days)
            if np.isnan(fr):
                continue
            scores[key] = s
            fwd[key] = fr

        if len(scores) < n_quantiles:
            continue

        keys = list(scores.keys())
        s_arr = np.array([scores[k] for k in keys])
        f_arr = np.array([fwd[k] for k in keys])

        # IC = Spearman rank correlation (score vs forward return)
        ic = _spearman(s_arr, f_arr)

        # Quantile buckets by score
        order = np.argsort(s_arr)
        ranked_f = f_arr[order]
        bucket = max(1, len(keys) // n_quantiles)
        bottom_ret = float(np.mean(ranked_f[:bucket]))
        top_ret = float(np.mean(ranked_f[-bucket:]))
        long_short = top_ret - bottom_ret
        bench = float(np.mean(f_arr))

        points.append(RebalancePoint(
            as_of=as_of.isoformat(), n_scored=len(keys), ic=_r(ic),
            top_return=_r(top_ret), bottom_return=_r(bottom_ret),
            long_short=_r(long_short), benchmark_return=_r(bench),
        ))
        ls_returns.append(long_short)
        bench_returns.append(bench)

    if not points:
        warnings.append("no valid rebalance points (insufficient history?)")
        return BacktestResult(
            market=market or "ALL", factor=factor,
            start=trading_dates[0].isoformat(), end=trading_dates[-1].isoformat(),
            rebalance_days=rebalance_days, holding_days=holding_days,
            n_quantiles=n_quantiles, n_rebalances=0, mean_ic=None, ic_hit_rate=None,
            mean_long_short=None, long_short_cum=None, benchmark_cum=None,
            sharpe_long_short=None, warnings=warnings,
        )

    ics = [p.ic for p in points if p.ic is not None]
    mean_ic = float(np.mean(ics)) if ics else None
    ic_hit = float(np.mean([1.0 if i > 0 else 0.0 for i in ics])) if ics else None
    mean_ls = float(np.mean(ls_returns)) if ls_returns else None
    ls_cum = float(np.prod([1 + r for r in ls_returns]) - 1) if ls_returns else None
    bench_cum = float(np.prod([1 + r for r in bench_returns]) - 1) if bench_returns else None
    sharpe = (
        float(np.mean(ls_returns) / np.std(ls_returns) * np.sqrt(252 / holding_days))
        if len(ls_returns) > 1 and np.std(ls_returns) > 0 else None
    )

    return BacktestResult(
        market=market or "ALL", factor=factor,
        start=points[0].as_of, end=points[-1].as_of,
        rebalance_days=rebalance_days, holding_days=holding_days,
        n_quantiles=n_quantiles, n_rebalances=len(points),
        mean_ic=_r(mean_ic), ic_hit_rate=_r(ic_hit), mean_long_short=_r(mean_ls),
        long_short_cum=_r(ls_cum), benchmark_cum=_r(bench_cum),
        sharpe_long_short=_r(sharpe), points=points, warnings=warnings,
    )


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman rank correlation without scipy dependency."""
    if len(a) < 3:
        return None
    ar = pd.Series(a).rank().to_numpy()
    br = pd.Series(b).rank().to_numpy()
    if np.std(ar) == 0 or np.std(br) == 0:
        return None
    return float(np.corrcoef(ar, br)[0, 1])


def _r(x: float | None, nd: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)
