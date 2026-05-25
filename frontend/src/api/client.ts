import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  timeout: 120_000, // 2분 — Render 무료 플랜 cold start 대응
});

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
  risk_detail: { penalties: Record<string, number>; partial: boolean };
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
  type: "news" | "disclosure";
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
