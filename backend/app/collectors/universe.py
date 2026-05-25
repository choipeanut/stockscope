"""Stock universe loader — KOSDAQ top + NASDAQ-100 configurable list."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_NASDAQ_CSV = _CONFIG_DIR / "nasdaq_universe.csv"

# Top KOSDAQ/KOSPI tickers by market cap (static fallback; refreshed when pykrx works)
# Reduced to 15 for screener performance on Render free tier
_KOSDAQ_TOP = [
    {"ticker": "005930", "name": "삼성전자"},
    {"ticker": "000660", "name": "SK하이닉스"},
    {"ticker": "207940", "name": "삼성바이오로직스"},
    {"ticker": "005380", "name": "현대차"},
    {"ticker": "035420", "name": "NAVER"},
    {"ticker": "068270", "name": "셀트리온"},
    {"ticker": "035720", "name": "카카오"},
    {"ticker": "247540", "name": "에코프로비엠"},
    {"ticker": "091990", "name": "셀트리온헬스케어"},
    {"ticker": "086520", "name": "에코프로"},
    {"ticker": "196170", "name": "알테오젠"},
    {"ticker": "263750", "name": "펄어비스"},
    {"ticker": "041510", "name": "에스엠"},
    {"ticker": "036570", "name": "엔씨소프트"},
    {"ticker": "112040", "name": "위메이드"},
]


def get_kosdaq_universe() -> list[dict]:
    """Return KOSDAQ universe as list of {ticker, market, name}."""
    return [
        {"ticker": item["ticker"], "market": "KOSDAQ", "name": item["name"]}
        for item in _KOSDAQ_TOP
    ]


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
