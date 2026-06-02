import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchPredict,
  fetchPredictEval,
  type PredictionRow,
} from "../api/client";

type MarketFilter = "" | "KR" | "KOSPI" | "KOSDAQ" | "NASDAQ";

const FEATURE_LABELS: Record<string, string> = {
  trend_alignment: "추세정렬",
  rsi: "RSI",
  macd: "MACD",
  volume: "거래량",
  relative_strength: "상대강도",
  high52w: "신고가근접",
  short_reversal: "단기반전",
  realized_vol: "저변동성",
  vol_ratio: "거래량비율",
  price_accel: "모멘텀가속",
  f_revenue_growth: "매출성장",
  f_profit_growth: "이익성장",
  f_roe: "ROE",
  f_op_margin: "영업이익률",
  f_debt_ratio: "부채비율",
};

function probColor(p: number): string {
  if (p >= 0.6) return "#22c55e";
  if (p >= 0.5) return "#84cc16";
  if (p >= 0.4) return "#f59e0b";
  return "#ef4444";
}

interface Props {
  onDrillDown?: (ticker: string, market: string) => void;
}

export function PredictPanel({ onDrillDown }: Props) {
  const [market, setMarket] = useState<MarketFilter>("");
  const [horizon, setHorizon] = useState(21);
  const [triggered, setTriggered] = useState(false);

  // Eval fires first (builds & caches dataset on server). Predict fires only
  // after eval is fully done. Both poll every 8s while status="running".
  const evalQ = useQuery({
    queryKey: ["predict-eval", market, horizon],
    queryFn: () => fetchPredictEval(market || undefined, horizon),
    enabled: triggered,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 8_000 : false,
  });

  const evalDone = evalQ.isSuccess && evalQ.data?.status !== "running" && !!evalQ.data?.report;

  const predict = useQuery({
    queryKey: ["predict", market, horizon],
    queryFn: () => fetchPredict(market || undefined, horizon),
    enabled: triggered && evalDone,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      (query.state.data as any)?.status === "running" ? 8_000 : false,
  });

  const rows: PredictionRow[] = (predict.data as any)?.status === "ok"
    ? (predict.data?.predictions ?? [])
    : [];
  const report = evalDone ? evalQ.data?.report : undefined;

  return (
    <div style={{ color: "#f9fafb" }}>
      <div style={{ marginBottom: 8 }}>
        <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>🔮 AI 예측 (실험적)</h2>
        <p style={{ color: "#9ca3af", fontSize: 13, marginTop: 6 }}>
          가격 기반 모멘텀 피처로 학습한 모델이 <b>다음 {horizon}거래일 동안 시장 대비 초과수익</b>을
          낼 확률을 추정합니다. Point-in-time 학습 · 미래 정보 누수 없음.
        </p>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 20 }}>
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value as MarketFilter)}
          style={selectStyle}
        >
          <option value="">전체</option>
          <option value="KR">한국 (코스피+코스닥)</option>
          <option value="NASDAQ">NASDAQ</option>
          <option value="KOSPI">KOSPI</option>
          <option value="KOSDAQ">KOSDAQ</option>
        </select>
        <select
          value={horizon}
          onChange={(e) => setHorizon(Number(e.target.value))}
          style={selectStyle}
        >
          <option value={5}>1주 (5일)</option>
          <option value={21}>1개월 (21일)</option>
          <option value={63}>3개월 (63일)</option>
        </select>
        <button
          onClick={() => {
            setTriggered(true);
            // eval runs first; predict auto-fires when eval succeeds (see enabled)
            evalQ.refetch();
          }}
          style={{
            background: "#3b82f6", border: "none", borderRadius: 8, color: "#fff",
            padding: "8px 20px", fontSize: 14, fontWeight: 600, cursor: "pointer",
          }}
        >
          예측 실행
        </button>
        {triggered && (evalQ.isFetching || evalQ.data?.status === "running") && (
          <span style={{ color: "#9ca3af", fontSize: 13 }}>⏳ 모델 검증 중… (자동 갱신)</span>
        )}
        {evalDone && (predict.isFetching || (predict.data as any)?.status === "running") && (
          <span style={{ color: "#9ca3af", fontSize: 13 }}>⏳ 종목 랭킹 생성 중… (자동 갱신)</span>
        )}
      </div>

      {/* Model honesty card */}
      {report && (
        <div style={{
          background: "#0c1322", border: "1px solid #1e3a5f", borderRadius: 12,
          padding: "14px 18px", marginBottom: 20,
        }}>
          <div style={{ fontSize: 13, color: "#93c5fd", fontWeight: 700, marginBottom: 8 }}>
            📊 모델 검증 (Out-of-Sample · 학습에 쓰지 않은 데이터)
          </div>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <Metric label="AUC" value={report.auc} hint="0.5=찍기 / 0.55+=실제 엣지" />
            <Metric label="정확도" value={report.accuracy} baseline={report.baseline_accuracy} />
            <Metric label="Rank IC" value={report.rank_ic} hint="예측력 상관" />
            <Metric label="테스트 표본" value={report.n_test} raw />
          </div>
          <p style={{ fontSize: 11, color: "#6b7280", margin: "10px 0 0" }}>
            AUC가 0.5 근처면 예측력이 거의 없는 것입니다. 0.7+ 처럼 너무 높으면 데이터 누수 의심.
            정직하게 표시합니다.
          </p>
        </div>
      )}

      {predict.error && (
        <div style={{ color: "#ef4444", padding: 12 }}>
          {(predict.error as Error).message}
        </div>
      )}

      {predict.data?.status === "insufficient_data" && (
        <div style={{ color: "#f59e0b", padding: 12 }}>
          학습 데이터가 부족합니다. 기간을 늘리거나 종목을 더 추가하세요.
        </div>
      )}

      {/* Ranking table */}
      {rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #374151", color: "#9ca3af" }}>
                <th style={{ ...th, textAlign: "left" }}>#</th>
                <th style={{ ...th, textAlign: "left" }}>종목</th>
                <th style={th}>초과수익 확률</th>
                {Object.values(FEATURE_LABELS).map((l) => (
                  <th key={l} style={th}>{l}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={`${r.ticker}-${r.market}`}
                  onClick={() => onDrillDown?.(r.ticker, r.market)}
                  style={{ borderBottom: "1px solid #1f2937", cursor: onDrillDown ? "pointer" : "default" }}
                >
                  <td style={{ ...td, color: "#6b7280" }}>{i + 1}</td>
                  <td style={{ ...td, textAlign: "left" }}>
                    <span style={{ fontWeight: 600 }}>{r.ticker}</span>
                    <span style={{ color: "#6b7280", marginLeft: 6 }}>{r.name}</span>
                    <span style={{
                      marginLeft: 6, fontSize: 10, color: "#6b7280",
                      border: "1px solid #374151", borderRadius: 4, padding: "1px 4px",
                    }}>{r.market}</span>
                  </td>
                  <td style={{ ...td, fontWeight: 700, color: probColor(r.probability) }}>
                    {(r.probability * 100).toFixed(1)}%
                  </td>
                  {Object.keys(FEATURE_LABELS).map((k) => (
                    <td key={k} style={{ ...td, color: "#9ca3af" }}>
                      {r.features[k]?.toFixed(0) ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {predict.data?.disclaimer && (
        <p style={{ marginTop: 16, fontSize: 11, color: "#6b7280", textAlign: "center" }}>
          ⚠️ {predict.data.disclaimer}
        </p>
      )}
    </div>
  );
}

function Metric({
  label, value, hint, baseline, raw,
}: { label: string; value: number | null; hint?: string; baseline?: number | null; raw?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>
        {value === null || value === undefined ? "—" : raw ? value : value.toFixed(3)}
      </div>
      {baseline != null && (
        <div style={{ fontSize: 10, color: "#6b7280" }}>기준선 {baseline.toFixed(3)}</div>
      )}
      {hint && <div style={{ fontSize: 10, color: "#6b7280" }}>{hint}</div>}
    </div>
  );
}

const selectStyle = {
  background: "#1f2937", border: "1px solid #374151", borderRadius: 8,
  color: "#f9fafb", padding: "8px 12px", fontSize: 14, outline: "none",
} as const;

const th = { padding: "8px 10px", textAlign: "right" as const, fontWeight: 600 };
const td = { padding: "8px 10px", textAlign: "right" as const };
