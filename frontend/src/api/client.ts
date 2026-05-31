import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  timeout: 120_000, // 2분 — Render 무료 플랜 cold start 대응
});

// JWT 토큰 자동 삽입
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 401 → 로그아웃 (토큰 만료 등)
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("auth_user");
      window.location.reload();
    }
    return Promise.reject(err);
  },
);

export interface OhlcvRow {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface FactorScores {
  fundamental: number | null;
  valuation: number | null;
  supply_demand: number | null;
  momentum: number | null;
  macro: number | null;
  risk: number | null;
  market_sentiment: number | null;
  analyst: number | null;
  insider: number | null;
  options: number | null;
}

export interface MarketSentimentDetail {
  market_score: number | null;
  market_trend: "bullish" | "bearish" | "neutral" | null;
  confidence: "high" | "medium" | "low" | null;
  summary: string;
  key_themes: string[];
  available: boolean;
}

export interface MomentumDetail {
  components: Record<string, number>;
  unavailable: string[];
}

export interface Scenario {
  stance: "bull" | "bear" | "neutral";
  probability_hint: "low" | "medium" | "high";
  reasons: string[];
  watch_conditions: string[];
}

export interface MacroDetail {
  regime: string;
  sector_hints: string[];
  components: Record<string, number | null>;
}

export interface SupplyDemandDetail {
  components: Record<string, number>;
  proxy: boolean;
}

export interface AnalyzeResponse {
  ticker: string;
  market: string;
  name: string;
  as_of: string;
  composite: number | null;
  composite_raw: number | null;
  sentiment_delta: number;
  sentiment: SentimentResult;
  factors: FactorScores;
  unavailable: string[];
  renormalized: boolean;
  key_required: string[];
  momentum_detail: MomentumDetail;
  valuation_detail: Record<string, number | null>;
  supply_demand_detail: SupplyDemandDetail;
  macro_detail: MacroDetail;
  risk_detail: { penalties: Record<string, number>; partial: boolean; components?: Record<string, number | null> };
  market_sentiment_detail: MarketSentimentDetail;
  analyst_detail: {
    mean_target: number | null;
    current_price: number | null;
    upside_pct: number | null;
    strong_buy: number;
    buy: number;
    hold: number;
    sell: number;
    strong_sell: number;
    num_analysts: number;
    upgrades_3m: number;
    downgrades_3m: number;
    available: boolean;
    components: Record<string, number>;
  };
  insider_detail: {
    buy_count: number;
    sell_count: number;
    buy_value: number | null;
    sell_value: number | null;
    net_value: number | null;
    available: boolean;
    components: Record<string, number>;
  };
  options_detail: {
    put_call_volume_ratio: number | null;
    put_call_oi_ratio: number | null;
    avg_iv: number | null;
    call_volume: number;
    put_volume: number;
    available: boolean;
    components: Record<string, number>;
  };
  scenarios: Scenario[];
  ohlcv: OhlcvRow[];
  notice: string;
}

export async function fetchAnalysis(ticker: string, market: string): Promise<AnalyzeResponse> {
  const { data } = await api.get<AnalyzeResponse>("/analyze", {
    params: { ticker, market },
  });
  return data;
}

export interface ScreenRow {
  ticker: string;
  market: string;
  name: string;
  composite: number | null;
  factors: FactorScores;
  unavailable: string[];
  renormalized: boolean;
  last_close: number | null;
  as_of: string;
}

export interface ScreenResponse {
  status: string;
  stale: boolean;
  total: number;
  results: ScreenRow[];
}

export interface SentimentResult {
  sentiment: "positive" | "negative" | "neutral";
  score_delta: number;
  confidence: "high" | "medium" | "low";
  summary: string;
  key_signals: string[];
  available: boolean;
  reason?: string;
}

export interface NewsItem {
  title: string;
  url: string;
  source: string;
  published: string;
  summary: string;
  type: "news" | "disclosure" | "macro_news";
}

export interface NewsResponse {
  ticker: string;
  market: string;
  news: NewsItem[];
  disclosures: NewsItem[];
  macro_news: NewsItem[];
  sentiment: SentimentResult;
  as_of: string;
}

export async function fetchNews(ticker: string, market: string, limit = 10): Promise<NewsResponse> {
  const { data } = await api.get<NewsResponse>("/news", {
    params: { ticker, market, limit },
  });
  return data;
}

export interface PricesResponse {
  ticker: string;
  market: string;
  ohlcv: OhlcvRow[];
}

export async function fetchPrices(
  ticker: string,
  market: string,
  days = 365,
): Promise<PricesResponse> {
  const { data } = await api.get<PricesResponse>("/prices", {
    params: { ticker, market, days },
  });
  return data;
}

export async function fetchScreen(
  market?: string,
  minScore?: number,
  limit?: number,
): Promise<ScreenResponse> {
  const { data } = await api.get<ScreenResponse>("/screen", {
    params: { market: market ?? "", min_score: minScore ?? 0, limit: limit ?? 50 },
    timeout: 180_000,
  });
  return data;
}
