"""Cache refresh service (T26).

Run as a one-off CLI command to pre-warm the TTL cache:

    python -m app.services.refresh [--market KOSDAQ|NASDAQ] [--limit N]

Or import and call `refresh_all()` from a scheduler / startup hook.
"""
from __future__ import annotations

import argparse
import logging
import time

logger = logging.getLogger(__name__)

# TTLs per data type (seconds) — must match the collector defaults
_TTL_MAP = {
    "prices_kosdaq": 5 * 60,
    "prices_nasdaq": 15 * 60,
    "fundamentals": 86_400,
    "valuation": 86_400,
    "flows": 86_400,
    "macro": 86_400,
    "risk": 86_400,
}

_THROTTLE = 0.5  # seconds between requests


def _refresh_ticker(ticker: str, market: str) -> dict:
    """Re-fetch all collectors for one ticker, repopulating the cache."""
    from app.collectors.flows import get_flows
    from app.collectors.fundamentals import get_fundamentals
    from app.collectors.prices import get_ohlcv
    from app.collectors.risk import get_risk
    from app.collectors.valuation import get_valuation

    results: dict[str, str] = {}

    for name, fn, kwargs in [
        ("prices", lambda: get_ohlcv(ticker, market, period_days=365), {}),
        ("fundamentals", lambda: get_fundamentals(ticker, market), {}),
        ("valuation", lambda: get_valuation(ticker, market), {}),
        ("flows", lambda: get_flows(ticker, market), {}),
    ]:
        try:
            fn()
            results[name] = "ok"
        except Exception as e:
            results[name] = f"err:{e}"
        time.sleep(_THROTTLE)

    # risk needs price df
    try:
        df = get_ohlcv(ticker, market, period_days=365)
        get_risk(ticker, market, price_df=df, index_df=None)
        results["risk"] = "ok"
    except Exception as e:
        results["risk"] = f"err:{e}"

    return results


def refresh_macro() -> dict:
    """Refresh global macro cache for both markets."""
    from app.collectors.macro import get_macro
    results = {}
    for market in ("NASDAQ", "KOSDAQ"):
        try:
            get_macro("", market)
            results[market] = "ok"
        except Exception as e:
            results[market] = f"err:{e}"
    return results


def refresh_universe(market: str | None = None, limit: int = 0) -> list[dict]:
    """
    Refresh cache for every ticker in the universe.

    Args:
        market: "KOSDAQ" | "NASDAQ" | None (both)
        limit: max tickers to refresh (0 = all)

    Returns:
        list of {ticker, market, results}
    """
    from app.collectors.universe import get_universe

    tickers = get_universe(market)
    if limit:
        tickers = tickers[:limit]

    report = []
    for i, item in enumerate(tickers):
        ticker, mkt = item["ticker"], item["market"]
        logger.info("[%d/%d] refreshing %s/%s", i + 1, len(tickers), ticker, mkt)
        res = _refresh_ticker(ticker, mkt)
        report.append({"ticker": ticker, "market": mkt, "results": res})

    return report


def refresh_all(market: str | None = None, limit: int = 0) -> dict:
    """Full cache warm: macro + universe."""
    macro = refresh_macro()
    universe = refresh_universe(market=market, limit=limit)
    ok = sum(1 for u in universe if all(v == "ok" for v in u["results"].values()))
    return {
        "macro": macro,
        "universe_total": len(universe),
        "universe_ok": ok,
        "universe_errors": len(universe) - ok,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Pre-warm StockScope TTL cache")
    parser.add_argument("--market", choices=["KOSDAQ", "NASDAQ"], default=None)
    parser.add_argument("--limit", type=int, default=0, help="Max tickers (0=all)")
    parser.add_argument("--macro-only", action="store_true")
    args = parser.parse_args()

    if args.macro_only:
        result = refresh_macro()
    else:
        result = refresh_all(market=args.market, limit=args.limit)

    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
