# Tasks

Execute one milestone at a time. Do not skip ahead. Do not continue past an `Approval: yes` gate without human approval. All scoring/data work must conform to ANALYSIS_SPEC.md.

---

## T1: Backend scaffold + health route
- Milestone: M1
- Depends on: —
- Files: `backend/app/main.py`, `backend/pyproject.toml`, `backend/app/__init__.py`
- Do: Create the FastAPI app with CORS enabled for the Vite dev origin and a `GET /health` route returning `{"status":"ok"}`. Pin dependencies from Tech Stack.
- Done when: `uvicorn app.main:app` starts and `curl localhost:8000/health` returns `{"status":"ok"}`.
- Verify: `curl -s localhost:8000/health | grep ok`
- Approval: no

## T2: Price collectors (KOSDAQ + NASDAQ)
- Milestone: M1
- Depends on: T1
- Files: `backend/app/collectors/prices.py`, `backend/app/collectors/cache.py`, `backend/tests/test_prices.py`
- Do: Implement `get_ohlcv(ticker, market, period)` returning a normalized OHLCV DataFrame (date, open, high, low, close, volume) — KOSDAQ via pykrx/finance-datareader, NASDAQ via yfinance. Add a simple file/SQLite TTL cache per ANALYSIS_SPEC §Caching. Normalize column names and timezone per spec.
- Done when: both a KOSDAQ ticker and a NASDAQ ticker return ≥120 rows with the normalized schema; second call within TTL is served from cache.
- Verify: `pytest backend/tests/test_prices.py` (asserts schema, row count, and cache hit on second call)
- Approval: no

## T3: Momentum sub-score
- Milestone: M1
- Depends on: T2
- Files: `backend/app/scoring/momentum.py`, `backend/tests/test_momentum.py`
- Do: Compute MA20/60/120 alignment, RSI(14), MACD signal state, volume surge, 52-week-high proximity, and relative strength vs index, then map to a 0–100 Momentum score exactly as ANALYSIS_SPEC §Momentum defines.
- Done when: momentum score and its component sub-scores are returned for a fixture price series and match the spec's golden numbers within ±1.
- Verify: `pytest backend/tests/test_momentum.py`
- Approval: no

## T4: Price-only composite + `/analyze` endpoint
- Milestone: M1
- Depends on: T3
- Files: `backend/app/scoring/composite.py`, `backend/app/api/analyze.py`
- Do: Build a composite that, for M1, uses only the price-computable factors (Momentum, plus any valuation/risk metric derivable from price) and clearly marks the other factors `unavailable`. Expose `GET /analyze?ticker=&market=` returning composite score, available sub-scores, and a freshness timestamp.
- Done when: `/analyze` returns valid JSON for one KOSDAQ and one NASDAQ ticker, with unavailable factors explicitly null-flagged (not zeroed).
- Verify: `curl "localhost:8000/analyze?ticker=AAPL&market=NASDAQ"` returns JSON with `composite`, `factors.momentum`, and `unavailable` list
- Approval: no

## T5: Frontend scaffold + score card + price chart
- Milestone: M1
- Depends on: T4
- Files: `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/components/ScoreCard.tsx`, `frontend/src/components/PriceChart.tsx`, `frontend/package.json`
- Do: Scaffold Vite+React+TS with a ticker/market input, a TanStack Query client calling `/analyze`, a ScoreCard (composite + factor bars + unavailable badges + freshness + disclaimer), and a Recharts price chart from `/analyze` OHLCV.
- Done when: entering `AAPL`/NASDAQ or `247540`/KOSDAQ renders the score card and a price chart with no console errors.
- Verify: manual — `npm run dev`, enter both tickers, confirm card + chart render; `npm run build` succeeds
- Approval: no

## T6: M1 integration and review
- Milestone: M1
- Depends on: T1, T2, T3, T4, T5
- Files: `backend/README.md` (M1 run notes), `frontend/README.md`
- Do: Wire backend + frontend end-to-end, document run commands, confirm the M1 user flow works for both markets.
- Done when: M1 done-criteria in AGENTS.md are met end-to-end.
- Verify: `pytest backend/` green; manual end-to-end on both markets
- Approval: yes — STOP. Human reviews M1 before proceeding.

---

## T7: Valuation collector + sub-score
- Milestone: M2
- Depends on: T6
- Files: `backend/app/collectors/valuation.py`, `backend/app/scoring/valuation.py`, `backend/tests/test_valuation.py`
- Do: Collect PER/PBR/PSR/EV-EBITDA/dividend yield (pykrx for KR PER/PBR/div, yfinance for US; compute the rest) plus the 5-year historical valuation position, then score per ANALYSIS_SPEC §Valuation (sector- and history-relative).
- Done when: valuation score + components return for a KR and a US fixture and match spec golden numbers within tolerance.
- Verify: `pytest backend/tests/test_valuation.py`
- Approval: no

## T8: Fundamental collector + sub-score
- Milestone: M2
- Depends on: T6
- Files: `backend/app/collectors/fundamentals.py`, `backend/app/scoring/fundamental.py`, `backend/tests/test_fundamental.py`
- Do: Collect growth (매출/EPS YoY), profitability (영업이익률, ROE, ROA), stability (부채비율, 이자보상배율), cash flow (영업CF, FCF), payout (배당, 자사주) — KR via OpenDartReader, US via yfinance — and score per ANALYSIS_SPEC §Fundamental.
- Done when: fundamental score returns for a US fixture with no key; KR path returns the score when a DART key is present and a clear `key required` flag when absent.
- Verify: `pytest backend/tests/test_fundamental.py` (US path asserted; KR path asserted only when `DART_API_KEY` env is set)
- Approval: no
- Blocked by: DART OpenAPI key (Needs Confirmation) for the KOSDAQ path.

## T9: Supply/demand collector + sub-score
- Milestone: M2
- Depends on: T6
- Files: `backend/app/collectors/flows.py`, `backend/app/scoring/supply_demand.py`, `backend/tests/test_flows.py`
- Do: KR — 외국인/기관/개인 순매수 (5/20일), 공매도 잔고·비중, 거래대금, 신용융자 via pykrx. US — volume trend + institutional ownership proxy via yfinance (document the KR/US asymmetry per spec). Score per ANALYSIS_SPEC §Supply-Demand.
- Done when: supply/demand score returns for a KR fixture (full inputs) and a US fixture (proxy inputs), each flagging which inputs are proxies.
- Verify: `pytest backend/tests/test_flows.py`
- Approval: no

## T10: Macro collector + sub-score
- Milestone: M2
- Depends on: T6
- Files: `backend/app/collectors/macro.py`, `backend/app/scoring/macro.py`, `backend/tests/test_macro_score.py`
- Do: Collect rates (기준금리, 10년물), FX (원/달러, DXY), CPI/PPI, PMI/GDP, commodities (유가, 구리), global indices (S&P500, NASDAQ, SOX, VIX) — FRED (US), ECOS (KR), yfinance (indices/commodities). Build a market-regime score and modulate by the stock's sensitivity profile per ANALYSIS_SPEC §Macro.
- Done when: macro score returns with a key; without keys it returns a `key required` flag and does not crash other factors.
- Verify: `pytest backend/tests/test_macro_score.py` (asserted only when keys present; absence path asserts graceful flag)
- Approval: no
- Blocked by: FRED key + ECOS key (Needs Confirmation).

## T11: Risk collector + sub-score
- Milestone: M2
- Depends on: T6
- Files: `backend/app/collectors/risk.py`, `backend/app/scoring/risk.py`, `backend/tests/test_risk.py`
- Do: Inputs — 부채/이자보상, 컨센서스 하향, 오버행 (CB/BW/보호예수), 감사의견, 변동성(ATR)·베타. KR disclosures/audit-opinion via OpenDartReader; volatility/beta computed from price. Score is **inverted** (100 = lowest risk) per ANALYSIS_SPEC §Risk.
- Done when: risk score returns for a US fixture (price-derived risk) and, with a DART key, includes KR disclosure flags.
- Verify: `pytest backend/tests/test_risk.py`
- Approval: no
- Blocked by: DART OpenAPI key for KR disclosure/audit inputs.

## T12: Weighted composite + scenario generator
- Milestone: M2
- Depends on: T7, T8, T9, T10, T11
- Files: `backend/app/scoring/composite.py`, `backend/app/scoring/scenarios.py`, `backend/tests/test_scoring.py`
- Do: Replace the M1 composite with the full weighted sum (펀더멘털30/밸류20/수급15/모멘텀15/거시10/리스크10) with renormalization when a factor is unavailable (per spec). Generate bull/bear/neutral scenarios with reason strings derived from actual factor states per ANALYSIS_SPEC §Scenario Generation.
- Done when: `/analyze` returns the weighted composite, all available sub-scores, an `unavailable`/renormalization note, and three scenarios each with ≥1 concrete reason; golden-number test passes.
- Verify: `pytest backend/tests/test_scoring.py`
- Approval: no

## T13: Frontend — full breakdown + scenarios + disclaimer
- Milestone: M2
- Depends on: T12
- Files: `frontend/src/components/FactorBreakdown.tsx`, `frontend/src/components/ScenarioPanel.tsx`, `frontend/src/App.tsx`
- Do: Render all six factor sub-scores (with unavailable badges), the three scenario panels with reasons, freshness timestamp, and the "not investment advice" notice.
- Done when: a real ticker shows all six factors and three scenarios with reasons; unavailable factors are visibly badged.
- Verify: manual — analyze a KR and a US ticker; confirm breakdown + scenarios render
- Approval: no

## T14: M2 integration and review
- Milestone: M2
- Depends on: T12, T13
- Files: `backend/README.md` (keys + scoring notes)
- Do: Verify the full 6-factor flow end-to-end, document required keys and the missing-data behavior.
- Done when: M2 done-criteria in AGENTS.md are met.
- Verify: `pytest backend/` green; manual end-to-end both markets
- Approval: yes — STOP. Human reviews M2 before proceeding.
- Blocked by: any still-unresolved DART/FRED/ECOS keys block the affected sub-scores in M4 screening.

---

## T15: SQLite schema + repository layer
- Milestone: M3
- Depends on: T14
- Files: `backend/app/db/schema.sql`, `backend/app/db/repo.py`, `backend/tests/test_repo.py`
- Do: Create tables `account(cash, base_currency)`, `holdings(ticker, market, qty, avg_price)`, `transactions(ts, ticker, market, side, qty, price)` per ANALYSIS_SPEC §Data/State Model, plus repo CRUD functions. Seed one account with virtual cash.
- Done when: repo can create the account, insert/read holdings and transactions, and survives a process restart.
- Verify: `pytest backend/tests/test_repo.py`
- Approval: no

## T16: Paper-trade service
- Milestone: M3
- Depends on: T15
- Files: `backend/app/services/paper_trading.py`, `backend/tests/test_paper_trading.py`
- Do: Implement `buy`/`sell` at the latest fetched price with validation (sufficient cash, sufficient shares), avg-price recompute, and realized/unrealized P&L per ANALYSIS_SPEC §Paper-Trading Rules. No slippage/commission (per Assumptions).
- Done when: buy then sell produces correct cash, holdings, avg price, and realized P&L; overselling and overspending are rejected with clear errors.
- Verify: `pytest backend/tests/test_paper_trading.py`
- Approval: no

## T17: `/portfolio` + `/trade` endpoints
- Milestone: M3
- Depends on: T16
- Files: `backend/app/api/portfolio.py`
- Do: `POST /trade` (side, ticker, market, qty) and `GET /portfolio` (cash, holdings with current price + unrealized P&L, totals).
- Done when: a trade via `/trade` is reflected in `/portfolio` with recomputed P&L.
- Verify: `curl -X POST localhost:8000/trade -d '{...}'` then `curl localhost:8000/portfolio` shows the position
- Approval: no

## T18: Frontend — portfolio + trade UI
- Milestone: M3
- Depends on: T17
- Files: `frontend/src/components/Portfolio.tsx`, `frontend/src/components/TradeForm.tsx`, `frontend/src/App.tsx`
- Do: A trade form (buy/sell from the analysis view) and a portfolio view (cash, holdings, per-position and total P&L). Refresh prices on load.
- Done when: a user buys from the analysis page and sees the position + P&L in the portfolio view.
- Verify: manual — buy a ticker, open portfolio, confirm holding + P&L
- Approval: no

## T19: M3 integration and review
- Milestone: M3
- Depends on: T16, T17, T18
- Files: `backend/README.md` (paper-trading notes)
- Do: Verify the full buy/sell/persist/P&L flow across both markets.
- Done when: M3 done-criteria in AGENTS.md are met and state persists across restart.
- Verify: `pytest backend/` green; manual buy → restart backend → portfolio persists
- Approval: yes — STOP. Human reviews M3 before proceeding.

---

## T20: Universe loader
- Milestone: M4
- Depends on: T19
- Files: `backend/app/collectors/universe.py`, `backend/tests/test_universe.py`, `backend/config/nasdaq_universe.csv`
- Do: Load the KOSDAQ ticker list from pykrx and the NASDAQ list from a configurable CSV (default NASDAQ-100). Expose `get_universe(market)`.
- Done when: both universes load with ticker + name; the NASDAQ list is swappable via the CSV.
- Verify: `pytest backend/tests/test_universe.py`
- Approval: no
- Blocked by: NASDAQ universe definition (Needs Confirmation) — only if a full listing rather than NASDAQ-100 is required.

## T21: Batch scoring with throttle + cache
- Milestone: M4
- Depends on: T20
- Files: `backend/app/services/screener.py`, `backend/tests/test_screener.py`
- Do: Score a universe by reusing the composite engine, with concurrency limits, per-source throttling, and snapshot caching per ANALYSIS_SPEC §Caching & Rate Limits. Skip/flag tickers with unavailable data rather than failing the batch.
- Done when: scoring a 20-ticker subset completes within the spec's batch budget and caches results; a single bad ticker does not abort the run.
- Verify: `pytest backend/tests/test_screener.py`
- Approval: no

## T22: `/screen` endpoint + watchlist
- Milestone: M4
- Depends on: T21
- Files: `backend/app/api/screen.py`, `backend/app/db/schema.sql` (add `watchlist`), `backend/app/db/repo.py`
- Do: `GET /screen?market=&min_score=&sort=&filters=` returns ranked results; `POST/GET/DELETE /watchlist` persists user picks.
- Done when: `/screen` returns a ranked, filtered list; watchlist add/remove persists.
- Verify: `curl "localhost:8000/screen?market=KOSDAQ&min_score=70"` returns sorted JSON; watchlist round-trips
- Approval: no

## T23: Frontend — screening table + drill-down + watchlist
- Milestone: M4
- Depends on: T22
- Files: `frontend/src/components/ScreenTable.tsx`, `frontend/src/components/Watchlist.tsx`, `frontend/src/App.tsx`
- Do: A sortable/filterable ranked table (composite + factor columns), one-click drill-down into the analysis view, and a watchlist panel.
- Done when: a user runs a screen, sorts/filters, clicks a row into analysis, and stars a ticker into the watchlist.
- Verify: manual — run screen, sort, drill down, add to watchlist
- Approval: no

## T24: M4 integration and review
- Milestone: M4
- Depends on: T21, T22, T23
- Files: `backend/README.md` (screening notes)
- Do: Verify the discovery flow end-to-end across KOSDAQ + NASDAQ.
- Done when: M4 done-criteria in AGENTS.md are met.
- Verify: `pytest backend/` green; manual screen → drill-down on both markets
- Approval: yes — STOP. Human reviews M4 before proceeding.

---

## T25: Macro dashboard + sector-rotation hint
- Milestone: M5
- Depends on: T24
- Files: `backend/app/api/macro.py`, `frontend/src/components/MacroDashboard.tsx`, `backend/tests/test_macro_api.py`
- Do: `GET /macro` aggregates the macro inputs into a current-regime summary and a sector-rotation hint by 경기 국면 (회복/확장/둔화/침체) per ANALYSIS_SPEC §Macro. Render a dashboard.
- Done when: `/macro` returns the regime + sector hints and the dashboard renders them (graceful flag when keys absent).
- Verify: `pytest backend/tests/test_macro_api.py`; manual dashboard render
- Approval: no

## T26: Scheduled cache refresh + freshness badges
- Milestone: M5
- Depends on: T25
- Files: `backend/app/services/refresh.py`, `frontend/src/components/FreshnessBadge.tsx`
- Do: A background/CLI refresh job for cached snapshots per the spec TTLs, plus a freshness badge component surfaced on analysis, portfolio, screen, and macro views.
- Done when: stale caches refresh on schedule/command and every data view shows its source timestamp.
- Verify: manual — trigger refresh, confirm timestamps update across views
- Approval: no

## T27: README + handoff
- Milestone: M5
- Depends on: T26
- Files: `README.md`
- Do: Document setup, required API keys (DART/FRED/ECOS), run/test/build commands, data-source delays, and known limitations (free-data delays, US flow proxies, no real-money trading).
- Done when: a new developer can set up and run the full app from the README alone.
- Verify: manual — follow README from a clean checkout to a running app
- Approval: no

## T28: M5 integration and final review
- Milestone: M5
- Depends on: T25, T26, T27
- Files: —
- Do: Full regression across all four flows (analyze, paper-trade, screen, macro) on both markets.
- Done when: all AGENTS.md "Done" must-pass checks are green.
- Verify: `pytest backend/` green; `ruff check .` + `npm run lint` clean; `npm run build` succeeds; manual end-to-end on both markets
- Approval: yes — STOP. Human final review.
