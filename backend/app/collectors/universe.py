"""Stock universe loader — KOSDAQ top + NASDAQ-100 configurable list."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_NASDAQ_CSV = _CONFIG_DIR / "nasdaq_universe.csv"

# Top KOSDAQ tickers by market cap (static fallback; refreshed when pykrx works)
_KOSDAQ_TOP50 = [
    "247540", "091990", "293490", "035900", "196170",
    "214150", "357780", "237690", "086520", "027410",
    "145020", "041510", "036570", "263750", "251270",
    "000660", "005930", "035420", "035720", "207940",
    "068270", "323410", "112040", "328130", "403870",
    "122630", "086820", "298050", "950130", "236200",
    "192820", "086960", "039030", "096530", "043360",
    "039200", "084370", "090460", "066570", "033600",
    "024060", "045890", "060310", "256840", "222080",
    "180640", "089030", "034220", "352820", "365550",
]


def _load_kosdaq_live() -> list[dict]:
    """Try pykrx for the top KOSDAQ market-cap list."""
    try:
        from datetime import datetime, timedelta

        from pykrx import stock

        today = datetime.today()
        for delta in range(5):
            date_str = (today - timedelta(days=delta)).strftime("%Y%m%d")
            try:
                df = stock.get_market_cap_by_ticker(date_str, market="KOSDAQ")
                if df is not None and not df.empty:
                    top = df.sort_values("시가총액", ascending=False).head(50)
                    return [
                        {"ticker": t, "market": "KOSDAQ", "name": ""}
                        for t in top.index.tolist()
                    ]
            except Exception:
                continue
    except Exception as e:
        logger.debug("pykrx market cap unavailable: %s", e)
    return []


def get_kosdaq_universe() -> list[dict]:
    """Return KOSDAQ universe as list of {ticker, market, name}."""
    live = _load_kosdaq_live()
    if live:
        return live
    return [{"ticker": t, "market": "KOSDAQ", "name": ""} for t in _KOSDAQ_TOP50]


def get_nasdaq_universe() -> list[dict]:
    """Return NASDAQ universe from config CSV, falling back to built-in top-20."""
    if _NASDAQ_CSV.exists():
        with open(_NASDAQ_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [
                {"ticker": row["ticker"], "market": "NASDAQ", "name": row.get("name", "")}
                for row in reader
            ]

    # Minimal built-in fallback
    _fallback = ["AAPL", "MSFT", "NVDA", "AMZN", "META",
                 "GOOGL", "TSLA", "AVGO", "COST", "NFLX"]
    return [{"ticker": t, "market": "NASDAQ", "name": ""} for t in _fallback]


def get_universe(market: str | None = None) -> list[dict]:
    """Return full or market-filtered universe."""
    if market == "KOSDAQ":
        return get_kosdaq_universe()
    if market == "NASDAQ":
        return get_nasdaq_universe()
    return get_kosdaq_universe() + get_nasdaq_universe()
