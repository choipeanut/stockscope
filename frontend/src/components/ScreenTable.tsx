import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchScreen, type ScreenRow } from "../api/client";

type SortKey = "composite" | "fundamental" | "valuation" | "momentum" | "supply_demand" | "macro" | "risk";
type MarketFilter = "" | "KOSDAQ" | "NASDAQ";

const FACTOR_LABELS: Record<string, string> = {
  fundamental: "펀더멘털",
  valuation: "밸류에이션",
  momentum: "모멘텀",
  supply_demand: "수급",
  macro: "매크로",
  risk: "리스크",
};

function scoreColor(v: number | null): string {
  if (v === null) return "#6b7280";
  if (v >= 70) return "#22c55e";
  if (v >= 45) return "#f59e0b";
  return "#ef4444";
}

function ScoreBadge({ value }: { value: number | null }) {
  return (
    <span
      style={{
        display: "inline-block",
        minWidth: 40,
        textAlign: "center",
        padding: "2px 6px",
        borderRadius: 4,
        fontSize: 13,
        fontWeight: 700,
        color: scoreColor(value),
        background: "transparent",
      }}
    >
      {value === null ? "—" : value.toFixed(1)}
    </span>
  );
}

interface Props {
  onDrillDown?: (ticker: string, market: string) => void;
}

export function ScreenTable({ onDrillDown }: Props) {
  const [market, setMarket] = useState<MarketFilter>("");
  const [minScore, setMinScore] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("composite");
  const [sortAsc, setSortAsc] = useState(false);

  const [triggered, setTriggered] = useState(false);

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["screen", market, minScore],
    queryFn: () => fetchScreen(market || undefined, minScore, 100),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    enabled: triggered,
    // 백그라운드 스코어링 중이면 15초마다 자동 폴링
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 15_000 : false,
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc((a) => !a);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  const rows: ScreenRow[] = data?.results
    ? [...data.results].sort((a, b) => {
        const av = sortKey === "composite"
          ? (a.composite ?? 0)
          : (a.factors[sortKey as keyof typeof a.factors] ?? 0);
        const bv = sortKey === "composite"
          ? (b.composite ?? 0)
          : (b.factors[sortKey as keyof typeof b.factors] ?? 0);
        return sortAsc ? av - bv : bv - av;
      })
    : [];

  function ColHeader({ k, label }: { k: SortKey; label: string }) {
    const active = sortKey === k;
    return (
      <th
        onClick={() => toggleSort(k)}
        style={{
          padding: "8px 10px",
          textAlign: "right",
          color: active ? "#93c5fd" : "#6b7280",
          fontWeight: 500,
          fontSize: 12,
          cursor: "pointer",
          whiteSpace: "nowrap",
          userSelect: "none",
        }}
      >
        {label} {active ? (sortAsc ? "↑" : "↓") : ""}
      </th>
    );
  }

  return (
    <div
      style={{
        background: "#111827",
        border: "1px solid #374151",
        borderRadius: 12,
        padding: 24,
        color: "#f9fafb",
      }}
    >
      {/* Controls */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 20 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, marginRight: 8 }}>종목 발굴 (스크리너)</h3>

        <select
          value={market}
          onChange={(e) => setMarket(e.target.value as MarketFilter)}
          style={{
            background: "#1f2937", border: "1px solid #374151", borderRadius: 6,
            color: "#f9fafb", padding: "6px 10px", fontSize: 13, outline: "none",
          }}
        >
          <option value="">전체 시장</option>
          <option value="KOSDAQ">KOSDAQ</option>
          <option value="NASDAQ">NASDAQ</option>
        </select>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12, color: "#9ca3af" }}>최소 점수</span>
          <input
            type="number"
            min={0}
            max={100}
            step={5}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            style={{
              width: 56,
              background: "#1f2937", border: "1px solid #374151", borderRadius: 6,
              color: "#f9fafb", padding: "6px 8px", fontSize: 13, outline: "none",
            }}
          />
        </div>

        <button
          onClick={() => { setTriggered(true); refetch(); }}
          disabled={isFetching || data?.status === "running"}
          style={{
            background: (isFetching || data?.status === "running") ? "#1f2937" : "#3b82f6",
            border: "none", borderRadius: 6, color: "#fff",
            padding: "7px 18px", fontSize: 13, fontWeight: 600,
            cursor: (isFetching || data?.status === "running") ? "not-allowed" : "pointer",
            opacity: (isFetching || data?.status === "running") ? 0.7 : 1,
          }}
        >
          {isFetching ? "⏳ 분석 중..." : "스크린 실행"}
        </button>

        {data?.stale && (
          <span style={{ fontSize: 12, color: "#f59e0b" }}>⚠ 이전 결과 표시 중</span>
        )}
        {data && !isFetching && (
          <span style={{ fontSize: 12, color: "#6b7280" }}>
            {data.total}개 종목 발견
          </span>
        )}
      </div>

      {error && (
        <div style={{
          background: "#2d0c0c", border: "1px solid #ef4444", borderRadius: 8,
          padding: "10px 14px", color: "#fca5a5", fontSize: 13, marginBottom: 16,
        }}>
          오류: {(error as Error).message}
        </div>
      )}

      {/* 백그라운드 스코어링 진행 중 */}
      {(data?.status === "running" || (isFetching && rows.length === 0)) && (
        <div style={{ textAlign: "center", padding: "32px 0" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔍</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#f9fafb", marginBottom: 6 }}>
            백그라운드에서 종목 스코어링 중...
          </div>
          <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 16 }}>
            처음 실행 시 1~3분 소요됩니다. 자동으로 새로고침합니다.
          </div>
          <div style={{
            display: "inline-block", background: "#1f2937",
            borderRadius: 8, padding: "8px 20px", fontSize: 12, color: "#9ca3af",
          }}>
            15초마다 자동 확인 중...
          </div>
        </div>
      )}

      {!isFetching && rows.length === 0 && data && (
        <div style={{ textAlign: "center", color: "#6b7280", padding: "24px 0", fontSize: 14 }}>
          조건에 맞는 종목이 없습니다. 스크린 실행을 눌러주세요.
        </div>
      )}

      {!isFetching && rows.length === 0 && !data && (
        <div style={{ textAlign: "center", color: "#6b7280", padding: "24px 0", fontSize: 14 }}>
          스크린 실행 버튼을 눌러 종목 발굴을 시작하세요.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #374151" }}>
                <th style={{ padding: "8px 10px", textAlign: "left", color: "#6b7280", fontWeight: 500, fontSize: 12 }}>종목</th>
                <th style={{ padding: "8px 10px", textAlign: "left", color: "#6b7280", fontWeight: 500, fontSize: 12 }}>시장</th>
                <ColHeader k="composite" label="종합" />
                <ColHeader k="fundamental" label={FACTOR_LABELS.fundamental} />
                <ColHeader k="valuation" label={FACTOR_LABELS.valuation} />
                <ColHeader k="momentum" label={FACTOR_LABELS.momentum} />
                <ColHeader k="supply_demand" label={FACTOR_LABELS.supply_demand} />
                <ColHeader k="macro" label={FACTOR_LABELS.macro} />
                <ColHeader k="risk" label={FACTOR_LABELS.risk} />
                <th style={{ padding: "8px 10px", textAlign: "right", color: "#6b7280", fontWeight: 500, fontSize: 12 }}>현재가</th>
                <th style={{ padding: "8px 10px", textAlign: "center", color: "#6b7280", fontWeight: 500, fontSize: 12 }}>분석</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${row.ticker}-${row.market}`}
                  style={{ borderBottom: "1px solid #1f2937" }}
                >
                  <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                    {row.ticker}
                    {row.name && (
                      <span style={{ display: "block", fontSize: 11, color: "#6b7280", fontWeight: 400 }}>
                        {row.name}
                      </span>
                    )}
                    {row.unavailable.length > 0 && (
                      <span style={{ fontSize: 10, color: "#92400e", marginLeft: 4 }}>
                        ({7 - row.unavailable.length}/7)
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "8px 10px", color: "#9ca3af" }}>{row.market}</td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.composite} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.fundamental} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.valuation} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.momentum} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.supply_demand} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.macro} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <ScoreBadge value={row.factors.risk} />
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right", color: "#d1d5db" }}>
                    {row.last_close !== null
                      ? row.last_close.toLocaleString(undefined, { maximumFractionDigits: 2 })
                      : "—"}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "center" }}>
                    {onDrillDown && (
                      <button
                        onClick={() => onDrillDown(row.ticker, row.market)}
                        style={{
                          background: "#1f2937", border: "1px solid #374151",
                          borderRadius: 5, color: "#93c5fd", padding: "3px 10px",
                          fontSize: 12, cursor: "pointer",
                        }}
                      >
                        분석
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
