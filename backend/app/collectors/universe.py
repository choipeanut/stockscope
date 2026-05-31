"""Stock universe loader — KOSDAQ top + NASDAQ-100 configurable list."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_NASDAQ_CSV = _CONFIG_DIR / "nasdaq_universe.csv"

# KOSPI 대형주 (삼성전자 등 거래소 상장)
_KOSPI_TOP = [
    {"ticker": "005930", "name": "삼성전자"},
    {"ticker": "000660", "name": "SK하이닉스"},
    {"ticker": "207940", "name": "삼성바이오로직스"},
    {"ticker": "005380", "name": "현대차"},
    {"ticker": "035420", "name": "NAVER"},
    {"ticker": "005490", "name": "POSCO홀딩스"},
    {"ticker": "000270", "name": "기아"},
    {"ticker": "105560", "name": "KB금융"},
    {"ticker": "055550", "name": "신한지주"},
    {"ticker": "028260", "name": "삼성물산"},
    {"ticker": "012330", "name": "현대모비스"},
    {"ticker": "066570", "name": "LG전자"},
    {"ticker": "003550", "name": "LG"},
    {"ticker": "034730", "name": "SK"},
    {"ticker": "017670", "name": "SK텔레콤"},
]

# KOSDAQ 대형주 (코스닥 상장)
_KOSDAQ_TOP = [
    {"ticker": "068270", "name": "셀트리온"},
    {"ticker": "035720", "name": "카카오"},
    {"ticker": "247540", "name": "에코프로비엠"},
    {"ticker": "086520", "name": "에코프로"},
    {"ticker": "196170", "name": "알테오젠"},
    {"ticker": "263750", "name": "펄어비스"},
    {"ticker": "041510", "name": "에스엠"},
    {"ticker": "036570", "name": "엔씨소프트"},
    {"ticker": "112040", "name": "위메이드"},
    {"ticker": "091990", "name": "셀트리온헬스케어"},
    {"ticker": "122870", "name": "와이지엔터테인먼트"},
    {"ticker": "095340", "name": "ISC"},
    {"ticker": "039030", "name": "이오테크닉스"},
    {"ticker": "214150", "name": "클래시스"},
    {"ticker": "145020", "name": "휴젤"},
]


def get_kosdaq_universe() -> list[dict]:
    """Return Korean market universe (KOSPI + KOSDAQ) as list of {ticker, market, name}."""
    kospi = [
        {"ticker": item["ticker"], "market": "KOSDAQ", "name": item["name"]}
        for item in _KOSPI_TOP
    ]
    kosdaq = [
        {"ticker": item["ticker"], "market": "KOSDAQ", "name": item["name"]}
        for item in _KOSDAQ_TOP
    ]
    return kospi + kosdaq


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
