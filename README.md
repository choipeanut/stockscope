# 📈 StockScope

KOSDAQ & NASDAQ 주식 분석 · 모의투자 · 종목 발굴 웹 애플리케이션

---

## 기능 요약

| 탭 | 설명 |
|---|---|
| **분석** | 종목 코드 입력 → 6-팩터 복합 점수 (0-100), 가격 차트, 시나리오 분석, 모의 투자 |
| **스크리너** | 전체 유니버스(KOSDAQ 50 + NASDAQ 50)를 일괄 스코어링해 순위표 제공 |
| **매크로** | 연준 금리·VIX·환율·PMI 등 거시 지표 대시보드 + 경기 국면 판단 |
| **포트폴리오** | 모의 투자 보유 현황, 평가손익, 가용 현금 |

---

## 6-팩터 복합 점수

| 팩터 | 기본 가중치 | 데이터 소스 |
|---|---|---|
| 펀더멘털 | 30% | DART API (KR) / yfinance (US) |
| 밸류에이션 | 20% | pykrx (KR) / yfinance (US) |
| 수급 | 15% | pykrx 투자자별 매매 (KR) / yfinance 거래량 (US) |
| 모멘텀 | 15% | pykrx / yfinance OHLCV |
| 거시환경 | 10% | FRED API + ECOS API + yfinance |
| 리스크 | 10% | DART 감사의견 + OHLCV 변동성 |

> 데이터를 구할 수 없는 팩터는 제외 후 나머지 가중치를 재정규화합니다.

---

## 설치 및 실행

### 필수 API 키

`backend/.env` 파일 생성:

```env
DART_API_KEY=<금융감독원 Open DART>
FRED_API_KEY=<St. Louis Fed FRED>
ECOS_API_KEY=<한국은행 ECOS>
```

모두 무료 회원가입으로 발급 가능합니다.

### 백엔드

```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| GET | `/analyze?ticker=&market=` | 단일 종목 6-팩터 분석 |
| GET | `/screen?market=&min_score=&limit=` | 유니버스 일괄 스크리닝 |
| GET | `/macro` | 거시경제 대시보드 지표 |
| GET | `/portfolio` | 모의 투자 포트폴리오 |
| POST | `/trade` | 모의 매수/매도 |
| GET | `/transactions` | 거래 내역 |
| GET | `/watchlist` | 관심 종목 |
| POST | `/watchlist` | 관심 종목 추가 |
| DELETE | `/watchlist/{id}` | 관심 종목 삭제 |
| GET | `/health` | 서버 상태 확인 |

---

## 프로젝트 구조

```
Stock_Claude/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 라우터 (analyze, portfolio, screen, macro)
│   │   ├── collectors/   # 데이터 수집 (prices, fundamentals, valuation, flows, macro, risk, universe)
│   │   ├── scoring/      # 팩터 스코어링 (composite, momentum, fundamental, valuation, supply_demand, macro_score, risk, scenarios)
│   │   ├── services/     # 비즈니스 로직 (paper_trading, screener)
│   │   └── db/           # SQLite repo (account, holdings, transactions, watchlist)
│   ├── config/
│   │   └── nasdaq_universe.csv  # NASDAQ 유니버스 편집 가능
│   ├── tests/            # pytest (paper_trading, momentum, prices)
│   └── data/             # SQLite DB + 캐시 (gitignored)
└── frontend/
    └── src/
        ├── api/           # client.ts (axios + 타입)
        └── components/    # ScoreCard, PriceChart, FactorBreakdown, ScenarioPanel,
                           # TradeForm, Portfolio, ScreenTable, MacroDashboard, FreshnessBadge
```

---

## 캐싱

SQLite TTL 캐시(`data/cache.db`)로 외부 API 호출을 최소화합니다.

| 데이터 | TTL |
|---|---|
| KOSDAQ OHLCV | 5분 |
| NASDAQ OHLCV | 15분 |
| 펀더멘털/밸류에이션 | 1일 |
| 수급/거시 | 1일 |

---

## 모의 투자

- 초기 가상 현금: **10,000,000원**
- 체결가: 최신 종가 (수수료·슬리피지 없음)
- 평균단가 자동 재계산 (추가 매수 시)
- SQLite 영구 저장 — 서버 재시작 후에도 보존

---

## ⚠️ 면책

본 애플리케이션의 점수와 시나리오는 **교육 목적**이며 투자 권유가 아닙니다.  
실제 투자 결정은 전문 금융인과 상담하세요.
