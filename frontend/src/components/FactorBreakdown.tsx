import type { AnalyzeResponse } from "../api/client";

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

interface RowProps {
  name: string;
  score: number | null;
  weight: number;
  unavailable: boolean;
  proxy?: boolean;
}

function FactorRow({ name, score, weight, unavailable, proxy }: RowProps) {
  const label = FACTOR_LABELS[name] ?? name;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontWeight: 500, fontSize: 14 }}>
          {label}{" "}
          <span style={{ color: "#6b7280", fontSize: 12 }}>({weight}%)</span>
          {proxy && (
            <span
              style={{
                fontSize: 10,
                background: "#1c1917",
                color: "#d97706",
                borderRadius: 3,
                padding: "1px 5px",
                marginLeft: 6,
              }}
            >
              proxy
            </span>
          )}
        </span>
        {unavailable ? (
          <span
            style={{
              fontSize: 11,
              background: "#1f2937",
              color: "#6b7280",
              borderRadius: 4,
              padding: "2px 8px",
            }}
          >
            데이터 없음
          </span>
        ) : (
          <span style={{ fontWeight: 700, color: scoreColor(score!), fontSize: 15 }}>
            {score?.toFixed(1)}
          </span>
        )}
      </div>
      <div style={{ background: "#1f2937", borderRadius: 4, height: 7 }}>
        {!unavailable && score !== null && (
          <div
            style={{
              width: `${score}%`,
              height: "100%",
              background: scoreColor(score),
              borderRadius: 4,
              transition: "width 0.5s ease",
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

export function FactorBreakdown({ data }: Props) {
  const { factors, unavailable, renormalized, supply_demand_detail } = data;
  const proxySD = supply_demand_detail?.proxy ?? false;

  return (
    <div>
      {renormalized && (
        <div
          style={{
            background: "#1f2937",
            border: "1px solid #374151",
            borderRadius: 6,
            padding: "8px 12px",
            marginBottom: 14,
            fontSize: 12,
            color: "#9ca3af",
          }}
        >
          일부 팩터 데이터 없음 — 가중치 재정규화 적용
        </div>
      )}
      {Object.entries(factors).map(([key, val]) => (
        <FactorRow
          key={key}
          name={key}
          score={val}
          weight={FACTOR_WEIGHTS[key] ?? 0}
          unavailable={unavailable.includes(key)}
          proxy={key === "supply_demand" && proxySD}
        />
      ))}
    </div>
  );
}
