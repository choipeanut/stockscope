# StockScope — KOSDAQ & NASDAQ Analysis, Paper Trading & Screening

Domain details → ANALYSIS_SPEC.md

## Goal
A web app that (1) analyzes individual stocks, (2) runs paper (virtual) trading, and (3) discovers promising stocks across **KOSDAQ (코스닥)** and **NASDAQ (나스닥)**. All analysis and screening MUST apply the multi-factor influence model defined in ANALYSIS_SPEC.md — 펀더멘털 / 밸류에이션 / 수급 / 모멘텀 / 거시환경 / 리스크 (weights 30/20/15/15/10/10) — computed on near-real-time, programmatically collectible data. Target user: a retail investor who wants an **explainable** 0–100 composite score with bull/bear/neutral scenarios, not a black-box buy/sell call. Success = enter a ticker → see the scored breakdown + scenarios, paper-trade it with virtual cash, and rank the universe by score.

## Tech Stack
- Backend: Python 3.11+, FastAPI, uvicorn
- Data libs: finance-datareader, pykrx, yfinance, OpenDartReader, fredapi, requests, pandas, numpy
- Storage: SQLite (portfolio, transactions, cached snapshots) via sqlite3 / SQLAlchemy
- Frontend: React 18 + Vite + TypeScript, TanStack Query, Recharts
- Run backend: `uvicorn app.main:app --reload` (from `backend/`)
- Run frontend: `npm run dev` (from `frontend/`)
- Test backend: `pytest` (from `backend/`)
- Lint: `ruff check .` (backend), `npm run lint` (frontend)

> Stack decision made by the generator. If the team prefers Next.js/Streamlit over Vite+FastAPI, flag it **before T1** — it changes every frontend task.

## Structure (greenfield — top level + initially touched files only)
- `backend/app/main.py`, `backend/app/collectors/prices.py`, `backend/app/scoring/momentum.py`, `backend/app/scoring/composite.py`, `backend/app/api/analyze.py`
- `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/components/ScoreCard.tsx`, `frontend/src/components/PriceChart.tsx`
- `data/` (SQLite db + cache files, gitignored)

Do not invent the full repo tree. Create subdirectories only when a task requires them.

## Non-Goals
- No real-money trading, no brokerage order routing, no payments.
- No investment advice and no guaranteed buy/sell recommendations — scores + scenarios + reasons only.
- No user accounts / auth / multi-tenant. Single local user for now.
- No sub-second real-time tick streaming. Free sources are delayed (see Assumptions).
- No mobile-native app, no deployment/hosting, no Docker in the MVP.
- No markets other than KOSDAQ and NASDAQ.
- No ML price-prediction model. ANALYSIS_SPEC §"Feature Candidates" is reference only and is OUT of MVP scope.

## Assumptions
### Safe
- "Near-real-time" = free public sources with documented delays: US prices ~15 min delayed (yfinance); KR prices intraday/EOD (pykrx, finance-datareader); financials are quarterly; macro is daily/monthly. Acceptable for the MVP.
- Display each market in its native currency (KRW for KOSDAQ, USD for NASDAQ). No portfolio-level FX conversion in the MVP.
- Paper-trade fills execute at the latest fetched price with no slippage/commission in M3 (commission model can be added later).
- KOSDAQ universe comes from pykrx; NASDAQ universe defaults to NASDAQ-100 unless configured otherwise.

### Needs Confirmation
- **DART OpenAPI key** (KR financials/disclosures) — blocks KOSDAQ fundamental & risk sub-scores (T8, T11).
- **FRED API key** (US macro) and **ECOS / 한국은행 key** (KR macro) — block the macro sub-score (T10).
- **True sub-minute real-time**: requires a paid feed (한국투자증권/Kiwoom OpenAPI, Polygon.io, etc.) — blocks any live-tick task. Not in current scope.
- **NASDAQ universe definition** (full listing vs NASDAQ-100 vs custom CSV) — blocks screening universe scope (T20).
- **News/sentiment source** (optional risk input) — if required, pick a provider; otherwise risk uses structured data only.

## Agent Rules
- Implement one milestone at a time, following TASKS.md order. Verify after each task; do not proceed on a failed check.
- Prefer executable verification (pytest + curl/HTTP checks). Use manual checks only for chart/visual behavior.
- Stop at every task marked `Approval: yes` and wait for human review.
- Do not add dependencies beyond Tech Stack without approval.
- **Never fabricate market data.** If a source returns empty/None, surface `"data unavailable"` for that factor — do not interpolate or invent numbers.
- All scoring math MUST match ANALYSIS_SPEC.md exactly (weights, normalization, factor→field→source mapping). If spec and runtime reality conflict, report the conflict instead of guessing.
- Cache every external call (see ANALYSIS_SPEC §Caching & Rate Limits) and throttle batch loops — never hammer a source in a tight loop.
- Every analysis view must show a data-freshness timestamp and a "not investment advice" notice.
- Do not refactor unrelated working code; do not expand scope beyond the current milestone.

## Milestones

### M1: Single-stock analysis MVP — ticker in, scored card out (no API keys)
- Scope: price collectors (KOSDAQ + NASDAQ), the Momentum sub-score, a price-only composite, a FastAPI `/analyze` endpoint, and a React page with a score card + interactive price chart.
- Done when: entering a KOSDAQ ticker (e.g., `247540`) or NASDAQ ticker (e.g., `AAPL`) returns a 0–100 score driven by price-computable factors plus a rendered price chart, with zero API keys required.
- Verify: `pytest backend/tests/test_momentum.py` passes; `curl "localhost:8000/analyze?ticker=AAPL&market=NASDAQ"` returns score JSON; manual: chart renders in browser.
- Human review: yes

### M2: Full 6-factor scoring + scenarios
- Scope: implement 펀더멘털 / 밸류에이션 / 수급 / 거시환경 / 리스크 sub-scores per ANALYSIS_SPEC, the weighted composite (30/20/15/15/10/10), and bull/bear/neutral scenario generation with explicit reasons.
- Done when: `/analyze` returns all six sub-scores (where keys are available), the weighted composite, and three scenarios each listing the factor drivers behind them; missing-data factors are flagged, never faked.
- Verify: `pytest backend/tests/test_scoring.py` (golden-number tests on a fixture stock); manual: scenarios + reasons render.
- Human review: yes
- Blocked by: DART / FRED / ECOS keys for the macro and KR-fundamental/risk sub-scores.

### M3: Paper trading (모의 투자)
- Scope: SQLite-backed virtual account (cash, holdings, transactions), buy/sell at current price, portfolio P&L and per-position returns.
- Done when: a user starts with virtual cash, buys/sells KOSDAQ + NASDAQ tickers, and sees holdings, realized/unrealized P&L, and a transaction history that persists across restarts.
- Verify: `pytest backend/tests/test_paper_trading.py`; manual: buy → refresh → P&L updates.
- Human review: yes

### M4: Screening / promising-stock discovery (유망 종목 발굴)
- Scope: score a configurable universe, rank by composite, filter by factor thresholds, and save a watchlist.
- Done when: a user runs a screen across the KOSDAQ + NASDAQ universe and gets a ranked, sortable, filterable table with one-click drill-down into the analysis view.
- Verify: `pytest backend/tests/test_screening.py`; manual: ranked table loads, sorts, and drills down.
- Human review: yes
- Blocked by: NASDAQ universe definition (T20) if a full listing rather than NASDAQ-100 is required.

### M5: Macro dashboard + freshness/handoff polish
- Scope: macro environment dashboard (rates / FX / CPI / global indices), sector-rotation hint by 경기 국면, scheduled cache refresh, data-freshness badges, and README.
- Done when: the macro dashboard renders the current regime + sector hints, every view shows a freshness timestamp, and the README documents setup, keys, and limitations.
- Verify: `pytest backend/tests/test_macro.py`; manual: dashboard + freshness badges render.
- Human review: yes

## Done
- Must-pass checks: backend pytest suite green; `ruff check .` and `npm run lint` clean; `/analyze`, `/portfolio`, `/trade`, `/screen` return valid JSON; `npm run build` succeeds.
- User-visible success: analyze any KOSDAQ/NASDAQ ticker with an explainable 6-factor score + scenarios, paper-trade it, and screen the universe for promising stocks.
- Handoff readiness: README with setup, required API keys, run/test commands, data-source delays, and known limitations.
- Still out of scope: real-money trading, auth, ML prediction, deployment, sub-minute real-time, markets beyond KOSDAQ/NASDAQ.
