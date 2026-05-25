# StockScope — Backend

## Setup

```bash
cd backend
pip install -e ".[dev]"
```

## Run

```bash
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`.

## Test

```bash
pytest                        # all tests
pytest tests/test_momentum.py # momentum unit tests only (no network)
```

## Lint

```bash
ruff check .
```

## M1 Endpoints (no API keys required)

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /analyze?ticker=AAPL&market=NASDAQ` | Price-only composite + momentum score + OHLCV |

### Response shape

```json
{
  "ticker": "AAPL",
  "market": "NASDAQ",
  "as_of": "2026-...",
  "composite": 74.9,
  "factors": {
    "fundamental": null,
    "valuation": null,
    "supply_demand": null,
    "momentum": 74.9,
    "macro": null,
    "risk": null
  },
  "unavailable": ["fundamental","valuation","supply_demand","macro","risk"],
  "renormalized": true,
  "momentum_detail": { "components": {...}, "unavailable": [] },
  "ohlcv": [...],
  "notice": "Not investment advice. Scores are educational only."
}
```

## Data Sources & Delays

| Data | Source | Delay |
|---|---|---|
| KOSDAQ OHLCV | pykrx | Intraday / EOD (cache TTL 5 min) |
| NASDAQ OHLCV | yfinance | ~15 min delayed (cache TTL 15 min) |

## Known Limitations (M1)

- Only the **Momentum** sub-score is computed (fully price-derived, no API keys needed).
- Fundamental / Valuation / Supply-Demand / Macro / Risk are marked `unavailable` until M2.
- KRX login warning from pykrx is harmless (no credentials needed for OHLCV).
- Composite score = Momentum score (renormalized) until M2 adds the other factors.
- No real-money trading. No investment advice.

## Required API Keys (future milestones)

| Key | Used by | Milestone |
|---|---|---|
| `DART_API_KEY` | KOSDAQ fundamentals, disclosures, risk | M2 |
| `FRED_API_KEY` | US macro (rates, CPI, PMI) | M2 |
| `ECOS_API_KEY` | KR macro (기준금리, CPI) | M2 |
