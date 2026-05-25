import type { AnalyzeResponse } from "../api/client";
import { FreshnessBadge } from "./FreshnessBadge";

const FACTOR_LABELS: Record<string, string> = {
  fundamental: "펀더멘털",
  valuation: "밸류에이션",
  supply_demand: "수급",
  momentum: "모멘텀",
  macro: "거시환경",
  risk: "리스크",
};

const FACTOR_WEIGHTS: Record<string, number> = {
  fundamental: 30,
  valuation: 20,
  supply_demand: 15,
  momentum: 15,
  macro: 10,
  risk: 10,
};

function scoreColor(score: number): string {
  if (score >= 70) return "#22c55e";
  if (score >= 45) return "#f59e0b";
  return "#ef4444";
}

interface FactorBarProps {
  name: string;
  score: number | null;
  weight: number;
  unavailable: boolean;
}

function FactorBar({ name, score, weight, unavailable }: FactorBarProps) {
  const label = FACTOR_LABELS[name] ?? name;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontWeight: 500 }}>
          {label}{" "}
          <span style={{ color: "#9ca3af", fontSize: 12 }}>({weight}%)</span>
        </span>
        {unavailable ? (
          <span style={{ fontSize: 12, background: "#374151", color: "#9ca3af", borderRadius: 4, padding: "2px 8px" }}>
            데이터 없음
          </span>
        ) : (
          <span style={{ fontWeight: 700, color: scoreColor(score!) }}>{score?.toFixed(1)}</span>
        )}
      </div>
      <div style={{ background: "#1f2937", borderRadius: 4, height: 8 }}>
        {!unavailable && score !== null && (
          <div
            style={{
              width: `${score}%`,
              height: "100%",
              background: scoreColor(score),
              borderRadius: 4,
              transition: "width 0.4s ease",
            }}
          />
        )}
      </div>
    </div>
  );
}

interface Props {
  data: AnalyzeResponse;
}

export function ScoreCard({ data }: Props) {
  const { composite, factors, unavailable, renormalized, as_of, ticker, market, notice } = data;
  const asOfDate = new Date(as_of).toLocaleString("ko-KR");

  return (
    <div
      style={{
        background: "#111827",
        border: "1px solid #374151",
        borderRadius: 12,
        padding: 24,
        color: "#f9fafb",
        maxWidth: 480,
        width: "100%",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
            {ticker}{" "}
            <span style={{ fontSize: 14, color: "#6b7280", fontWeight: 400 }}>{market}</span>
          </h2>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <span>기준: {asOfDate}</span>
            <FreshnessBadge asOf={as_of} staleAfterMinutes={30} />
          </div>
        </div>
        {composite !== null && (
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: "50%",
              border: `4px solid ${scoreColor(composite)}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexDirection: "column",
            }}
          >
            <span style={{ fontSize: 22, fontWeight: 800, color: scoreColor(composite) }}>
              {composite.toFixed(0)}
            </span>
            <span style={{ fontSize: 10, color: "#9ca3af" }}>/ 100</span>
          </div>
        )}
      </div>

      {renormalized && (
        <div
          style={{
            background: "#1f2937",
            border: "1px solid #374151",
            borderRadius: 6,
            padding: "8px 12px",
            marginBottom: 16,
            fontSize: 12,
            color: "#9ca3af",
          }}
        >
          일부 팩터 데이터가 없어 가중치를 재정규화했습니다.
        </div>
      )}

      {/* Factor bars */}
      {Object.entries(factors).map(([key, val]) => (
        <FactorBar
          key={key}
          name={key}
          score={val}
          weight={FACTOR_WEIGHTS[key] ?? 0}
          unavailable={unavailable.includes(key)}
        />
      ))}

      {/* Disclaimer */}
      <div
        style={{
          marginTop: 20,
          padding: "10px 12px",
          background: "#1f2937",
          borderRadius: 6,
          fontSize: 11,
          color: "#6b7280",
          borderLeft: "3px solid #374151",
        }}
      >
        ⚠️ {notice}
      </div>
    </div>
  );
}
