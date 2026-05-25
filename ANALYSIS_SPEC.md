# Analysis Spec

Dense technical reference for the scoring engine, data sources, paper-trading state, and screening. The composite model is the literal encoding of the uploaded influence-factor document. Do not duplicate goals, non-goals, milestones, or task lists here.

---

## Data Sources & Field Mapping

All collectors return normalized objects with `value`, `source`, `as_of` (UTC timestamp), and `available: bool`. If a source returns empty/None, set `available=false` — never substitute a fabricated value.

| Domain | KOSDAQ source | NASDAQ source | Notes |
|---|---|---|---|
| OHLCV / price | pykrx, finance-datareader | yfinance | KR intraday/EOD; US ~15 min delayed |
| Valuation (PER/PBR/배당) | pykrx `get_market_fundamental` | yfinance `info` / computed | PSR, EV/EBITDA, PEG computed from financials |
| Fundamentals (재무) | OpenDartReader (DART) | yfinance financials/cashflow | KR requires `DART_API_KEY` |
| Flows (수급) | pykrx investor net-buy, short-selling, credit balance | yfinance volume + institutional ownership (proxy) | KR has 외국인/기관/개인 split; US does not — use proxy and flag it |
| Macro | ECOS (한국은행) | FRED | indices/commodities via yfinance for both |
| Risk / disclosures | OpenDartReader (공시, 감사의견, CB/BW) | yfinance (beta) + price volatility | KR disclosure inputs require `DART_API_KEY` |
| Universe | pykrx KOSDAQ list | configurable CSV (default NASDAQ-100) | |

Normalization rules: rename OHLCV columns to `date, open, high, low, close, volume`; index by date ascending; KR prices in KRW, US in USD; store `market ∈ {KOSDAQ, NASDAQ}` on every record.

---

## Composite Score Model

```
composite = 0.30*fundamental + 0.20*valuation + 0.15*supply_demand
          + 0.15*momentum + 0.10*macro + 0.10*risk
```

- Every sub-score is **0–100, higher = better**. `risk` is **inverted** (100 = lowest risk).
- **Missing-factor renormalization:** if a factor is `unavailable`, drop its weight and renormalize the remaining weights to sum to 1.0. Return the dropped factors in an `unavailable[]` list and a `renormalized: true` flag. Never zero-fill an unavailable factor (zero ≠ unknown).
- **Normalization primitive** (`norm`): for relative metrics, percentile-rank the value within its comparison set (sector peers for fundamental/valuation; market universe for momentum/flows) → 0–100. For absolute-threshold metrics, use the banded tables below. Higher-is-worse metrics (부채비율, PER) are inverted before ranking.
- A sub-score equals the weighted mean of its component scores; component weights are given per factor below and sum to 1.0 within the factor.

### Fundamental (펀더멘털) — weight 0.30
| Component | Fields | Sub-weight | Direction |
|---|---|---|---|
| 성장성 | 매출 성장률 YoY, EPS 성장률 | 0.25 | higher better |
| 수익성 | 영업이익률, ROE, ROA | 0.25 | higher better |
| 안정성 | 부채비율, 이자보상배율 | 0.20 | 부채비율 lower better; 이자보상 higher better |
| 현금흐름 | 영업현금흐름, FCF | 0.20 | higher better; OCF<0 or FCF<0 caps component ≤ 30 |
| 주주환원 | 배당성향, 자사주 매입·소각 | 0.10 | higher better |

### Valuation (밸류에이션) — weight 0.20
| Component | Fields | Sub-weight | Direction |
|---|---|---|---|
| PER | 업종 대비 PER | 0.25 | lower better (invert) |
| PBR | PBR (read with ROE) | 0.15 | lower better, but low-PBR+low-ROE not rewarded |
| PSR | PSR (for 적자 성장주) | 0.15 | lower better |
| EV/EBITDA | EV/EBITDA | 0.20 | lower better |
| 배당수익률 | dividend yield | 0.10 | higher better |
| 과거 위치 | current vs 5y avg PER/PBR percentile | 0.15 | lower-in-range better |

### Supply-Demand (수급) — weight 0.15
| Component | KR fields | US proxy | Sub-weight |
|---|---|---|---|
| 외국인 | 외국인 순매수 5일/20일 | institutional ownership Δ | 0.30 |
| 기관 | 기관 순매수 5일/20일 | — (fold into volume trend) | 0.20 |
| 개인 과열(역신호) | 개인 매수 집중 | retail-proxy n/a | 0.10 |
| 거래대금 | 평균 대비 증가율 | volume vs avg | 0.20 |
| 공매도(역신호) | 공매도 잔고·비중 | short interest (if available) | 0.20 |
US note: KR-only inputs are flagged `proxy=true`; the US sub-score reweights available components.

### Momentum (모멘텀) — weight 0.15 (fully price-computable, no keys)
| Component | Logic | Sub-weight |
|---|---|---|
| 추세 정렬 | close>MA20>MA60>MA120 → high; inverse alignment → low | 0.30 |
| RSI(14) | 45–65 healthy; >75 overbought penalty; <30 oversold mild | 0.15 |
| MACD | signal-line cross state + histogram sign | 0.15 |
| 거래량 | breakout confirmed by volume surge (vol > 1.5× MA20vol) | 0.15 |
| 상대강도 | stock 60d return − index 60d return (KOSPI/NASDAQ) | 0.15 |
| 신고가 근접 | distance to 52-week high | 0.10 |

### Macro (거시환경) — weight 0.10 (market-level, then per-stock modulation)
1. Build a **regime score** from: rate trend (기준금리, 10y), yield-curve slope (장단기차), FX (원/달러, DXY), CPI/PPI trend, PMI/GDP, commodities (유가, 구리), indices (S&P500, NASDAQ, SOX), VIX.
2. Determine 경기 국면 ∈ {회복, 확장, 둔화, 침체} from PMI + yield curve + index trend.
3. **Per-stock modulation** by sensitivity profile (derived from sector + beta + 수출/내수 tag):
   - 성장주/기술주: penalized when rates rising; rewarded when falling.
   - 수출주(반도체/자동차/조선/방산): rewarded on 원화 약세; 내수/항공/수입원가주 inverse.
   - 방어주(헬스케어/필수소비/통신): rewarded in 둔화/침체.
4. macro_score = regime_score adjusted by the stock's sensitivity multipliers, clamped 0–100.

### Risk (리스크) — weight 0.10, **inverted (100 = safest)**
Start at 100, subtract penalties:
| Risk input | Penalty trigger | Max penalty |
|---|---|---|
| 부채 위험 | 부채비율 high / 이자보상배율 < 1 | −25 |
| 실적 하향 | consensus EPS/목표주가 하향 (최근 1M) | −15 |
| 오버행 | CB/BW 미상환, 보호예수 해제 임박 | −20 |
| 회계 위험 | 감사의견 비적정/한정, 거래정지 이력 | −30 |
| 뉴스 리스크 | 소송·규제·횡령 공시 (optional source) | −15 |
| 변동성 | ATR%/베타 high | −15 |
risk_score = clamp(100 − Σpenalties, 0, 100). KR disclosure penalties need `DART_API_KEY`; without it, compute price-derived (변동성/베타) only and flag partial.

---

## Scenario Generation

Emit three scenarios; each lists only the reasons whose underlying factor states are actually true (from the doc's final-section logic). Never emit a reason that the data does not support.

- **Bull (상승):** triggers from {실적/펀더멘털 상향, 외국인·기관 순매수, 모멘텀 추세 정렬/거래량 돌파, 우호적 macro}. Reason strings cite the specific factor + value.
- **Bear (하락):** triggers from {실적 하향, 고평가(밸류 하위), 공매도 증가, 금리 상승/macro 역풍, 지지선 이탈(추세 붕괴)}.
- **Neutral (중립):** when signals conflict, e.g., strong fundamentals but stretched valuation, or weak flows / pending event (실적·이벤트 대기).

Output shape per scenario: `{ stance, probability_hint: low|medium|high, reasons: string[], watch_conditions: string[] }`. `watch_conditions` = "what would flip the call" (e.g., "외국인 5일 순매수 전환", "20일선 회복").

---

## Data / State Model (Paper Trading)

```sql
account(id INTEGER PK, cash REAL NOT NULL, base_currency TEXT NOT NULL); -- single row for MVP
holdings(id INTEGER PK, ticker TEXT, market TEXT, qty REAL, avg_price REAL,
         UNIQUE(ticker, market));
transactions(id INTEGER PK, ts TEXT, ticker TEXT, market TEXT,
             side TEXT CHECK(side IN ('BUY','SELL')), qty REAL, price REAL);
watchlist(id INTEGER PK, ticker TEXT, market TEXT, added_ts TEXT, UNIQUE(ticker,market));
cache(key TEXT PK, payload TEXT, as_of TEXT, ttl_seconds INTEGER);
```

### Paper-Trading Rules
- Fill at the latest fetched close/price for the ticker's market. No slippage/commission in M3.
- BUY: require `cash >= qty*price`; decrement cash; recompute `avg_price = (old_qty*old_avg + qty*price)/(old_qty+qty)`.
- SELL: require `holding.qty >= qty`; increment cash; **realized P&L** `= (price − avg_price)*qty`; avg_price unchanged; delete row when qty hits 0.
- **Unrealized P&L** per position `= (current_price − avg_price)*qty`. Reject overspend/oversell with explicit errors.
- Each market is valued in its own currency; no cross-currency netting in the MVP.

---

## Interfaces / Contracts

- `GET /analyze?ticker=&market=` → `{ ticker, market, as_of, composite, factors:{fundamental,valuation,supply_demand,momentum,macro,risk}, unavailable:[], renormalized:bool, scenarios:[bull,bear,neutral], ohlcv:[...] }`
- `POST /trade` body `{ side, ticker, market, qty }` → updated `{ account, holding }` or `{ error }`.
- `GET /portfolio` → `{ cash, base_currency, holdings:[{ticker,market,qty,avg_price,current_price,unrealized_pnl}], totals }`
- `GET /screen?market=&min_score=&sort=&filters=` → ranked `[{ ticker, name, composite, factors }]` (unavailable-data tickers flagged, not dropped silently unless filtered).
- `GET /macro` → `{ regime, phase, sector_hints:[], inputs:{...}, as_of }`
- Watchlist: `POST /watchlist {ticker,market}`, `GET /watchlist`, `DELETE /watchlist/{id}`.

All responses include `as_of` and respect the "not investment advice" contract on the client.

---

## Caching & Rate Limits

| Data | TTL | Reason |
|---|---|---|
| OHLCV (US) | 15 min | source delay |
| OHLCV (KR) | 5 min intraday / EOD after close | source cadence |
| Valuation | 1 day | daily refresh |
| Fundamentals | 1 day (quarterly underlying) | quarterly filings |
| Flows | 1 hour | EOD-ish update |
| Macro | 1 day | daily/monthly series |
| Screen snapshots | 6 hours | batch reuse |

Batch scoring: max concurrency 4, per-source min interval 0.3 s, exponential backoff on rate-limit/HTTP 429. A failed ticker is skipped + flagged; it must not abort the batch.

---

## Edge Cases / Errors
- Unknown/delisted ticker → 404 with `{error:"ticker not found"}`; never guess a near-match.
- Source down / rate-limited → serve last cached value with a stale flag; if no cache, factor `unavailable`.
- Missing API key → affected factor `unavailable` + `key_required:"DART|FRED|ECOS"`; other factors still compute.
- New listing with <120 price rows → momentum components that need MA120 are `unavailable`, not zero.
- KR holiday / pre-open → return last trading day's data with `as_of` reflecting it.
- US-only proxy flows → mark `proxy:true` so the UI can disclose it.

---

## Performance Targets
- Single `/analyze` (warm cache): < 1.5 s; cold (network): < 6 s.
- `/screen` over 100 tickers (warm): < 8 s; cold: bounded by throttle, show progressive/partial results.
- Frontend first analysis render: < 2 s after response. SQLite writes: < 50 ms.

---

## Risks and Measurement
- **Data-source breakage** (pykrx/yfinance schema drift): contract tests in collector test files assert normalized schema; CI surfaces drift.
- **Rate limiting** during screening: measured by 429 count per run; backoff keeps it at 0 in the verify suite.
- **Scoring drift**: golden-number tests on fixture stocks pin each sub-score; any change must update fixtures intentionally.
- **Stale data presented as live**: every response carries `as_of`; freshness badge required on all views (M5).

---

## Feature Candidates (REFERENCE ONLY — OUT OF MVP SCOPE)
The influence-factor document's predictive-model feature list (가격/기술적/재무/밸류/수급/거시/뉴스/이벤트 features) is recorded here as a future ML reference. No ML model is built in this project. Do not implement training or prediction code in any milestone.
