import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  timeout: 10_000,
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
