import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { FreshnessBadge } from "./FreshnessBadge";

interface MacroData {
  as_of: string;
  regime: string;
  sector_hints: string[];
  fred_available: boolean;
  ecos_available: boolean;
  indicators: {
    fed_rate: number | null;
    us_10y: number | null;
    yield_curve: number | null;
    bok_rate: number | null;
    usdkrw: number | null;
    dxy: number | null;
    us_cpi: number | null;
    kr_cpi: number | null;
    vix: number | null;
    us_pmi: number | null;
    sp500_60d: number | null;
    nasdaq_60d: number | null;
    sox_60d: number | null;
    oil: number | null;
    copper: number | null;
  };
}

const REGIME_COLOR: Record<string, string> = {
  확장: "#22c55e",
  회복: "#3b82f6",
  둔화: "#f59e0b",
  침체: "#ef4444",
};

interface IndicatorGroupItem {
  key: string;
  label: string;
  fmt: (v: number) => string;
  colorize?: boolean;
  invert?: boolean;
}

interface IndicatorGroup {
  label: string;
  items: IndicatorGroupItem[];
}

const INDICATOR_GROUPS: IndicatorGroup[] = [
  {
    label: "💵 미국 금리·채권",
    items: [
      { key: "fed_rate", label: "연준 기준금리", fmt: (v: number) => `${v.toFixed(2)}%` },
      { key: "us_10y", label: "미국 10년물", fmt: (v: number) => `${v.toFixed(2)}%` },
      {
        key: "yield_curve",
        label: "장단기 스프레드(10y-2y)",
        fmt: (v: number) => `${v.toFixed(2)}%`,
        colorize: true,
      },
    ],
  },
  {
    label: "🇰🇷 한국 금리·환율",
    items: [
      { key: "bok_rate", label: "한국은행 기준금리", fmt: (v: number) => `${v.toFixed(2)}%` },
      { key: "usdkrw", label: "USD/KRW", fmt: (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 1 }) },
      { key: "dxy", label: "달러 인덱스(DXY)", fmt: (v: number) => v.toFixed(2) },
    ],
  },
  {
    label: "📈 경기·인플레이션",
    items: [
      { key: "us_cpi", label: "미국 CPI 지수", fmt: (v: number) => v.toFixed(1) },
      { key: "kr_cpi", label: "한국 CPI 지수", fmt: (v: number) => v.toFixed(1) },
      { key: "us_pmi", label: "미국 PMI", fmt: (v: number) => v.toFixed(1), colorize: true },
    ],
  },
  {
    label: "😰 리스크·변동성",
    items: [
      {
        key: "vix",
        label: "VIX (공포지수)",
        fmt: (v: number) => v.toFixed(2),
        colorize: true,
        invert: true,
      },
      { key: "sp500_60d", label: "S&P500 60일 수익률", fmt: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, colorize: true },
      { key: "nasdaq_60d", label: "NASDAQ 60일 수익률", fmt: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, colorize: true },
    ],
  },
  {
    label: "🏭 원자재·반도체",
    items: [
      { key: "sox_60d", label: "필라델피아 반도체 60일", fmt: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, colorize: true },
      { key: "oil", label: "WTI 원유 ($/bbl)", fmt: (v: number) => `$${v.toFixed(1)}` },
      { key: "copper", label: "구리 선물 ($/lb)", fmt: (v: number) => `$${v.toFixed(3)}` },
    ],
  },
];

function indColor(v: number, colorize?: boolean, invert?: boolean): string {
  if (!colorize) return "#f9fafb";
  const positive = invert ? v < 20 : v > 0;
  const negative = invert ? v > 30 : v < 0;
  if (positive) return "#22c55e";
  if (negative) return "#ef4444";
  return "#f59e0b";
}

function IndicatorCard({
  label,
  value,
  fmt,
  colorize,
  invert,
}: {
  label: string;
  value: number | null;
  fmt: (v: number) => string;
  colorize?: boolean;
  invert?: boolean;
}) {
  const text = value !== null ? fmt(value) : "—";
  const color = value !== null ? indColor(value, colorize, invert) : "#6b7280";
  return (
    <div
      style={{
        background: "#1f2937",
        borderRadius: 8,
        padding: "10px 14px",
        minWidth: 140,
        flex: "1 1 140px",
      }}
    >
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{label}</div>
      <div style={{ fontWeight: 700, fontSize: 15, color }}>{text}</div>
    </div>
  );
}

export function MacroDashboard() {
  const { data, isFetching, error, refetch } = useQuery<MacroData>({
    queryKey: ["macro"],
    queryFn: async () => (await api.get("/macro")).data,
    staleTime: 60 * 60 * 1000, // 1 hour
    refetchOnWindowFocus: false,
  });

  const regimeColor = data?.regime ? (REGIME_COLOR[data.regime] ?? "#9ca3af") : "#9ca3af";

  return (
    <div style={{ color: "#f9fafb", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header */}
      <div
        style={{
          background: "#111827",
          border: "1px solid #374151",
          borderRadius: 12,
          padding: 24,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
          <div>
            <h3 style={{ margin: "0 0 12px", fontSize: 16, fontWeight: 600 }}>거시경제 대시보드</h3>
            {data?.regime && (
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 13, color: "#6b7280" }}>현재 경기 국면</span>
                <span
                  style={{
                    fontSize: 24, fontWeight: 800, color: regimeColor,
                    padding: "2px 14px", background: `${regimeColor}22`,
                    borderRadius: 8, border: `1px solid ${regimeColor}55`,
                  }}
                >
                  {data.regime}
                </span>
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              style={{
                background: "#1f2937", border: "1px solid #374151", borderRadius: 6,
                color: "#9ca3af", padding: "5px 14px", fontSize: 12, cursor: "pointer",
              }}
            >
              {isFetching ? "갱신 중..." : "새로고침"}
            </button>
            {data?.as_of && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 11, color: "#4b5563" }}>
                  기준: {new Date(data.as_of).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}
                </span>
                <FreshnessBadge asOf={data.as_of} staleAfterMinutes={60} />
              </div>
            )}
            <div style={{ display: "flex", gap: 6 }}>
              <span
                style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 4,
                  background: data?.fred_available ? "#052e16" : "#1c1917",
                  color: data?.fred_available ? "#4ade80" : "#78716c",
                  border: `1px solid ${data?.fred_available ? "#166534" : "#44403c"}`,
                }}
              >
                FRED {data?.fred_available ? "✓" : "✗"}
              </span>
              <span
                style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 4,
                  background: data?.ecos_available ? "#052e16" : "#1c1917",
                  color: data?.ecos_available ? "#4ade80" : "#78716c",
                  border: `1px solid ${data?.ecos_available ? "#166534" : "#44403c"}`,
                }}
              >
                ECOS {data?.ecos_available ? "✓" : "✗"}
              </span>
            </div>
          </div>
        </div>

        {/* Sector hints */}
        {data?.sector_hints && data.sector_hints.length > 0 && (
          <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: "#6b7280", alignSelf: "center" }}>섹터 힌트:</span>
            {data.sector_hints.map((h, i) => (
              <span
                key={i}
                style={{
                  background: "#1f2937", borderRadius: 6,
                  padding: "4px 12px", fontSize: 12, color: "#d1d5db",
                  border: "1px solid #374151",
                }}
              >
                {h}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div style={{
          background: "#2d0c0c", border: "1px solid #ef4444", borderRadius: 8,
          padding: "10px 14px", color: "#fca5a5", fontSize: 13,
        }}>
          오류: {(error as Error).message}
        </div>
      )}

      {/* Indicator groups */}
      {INDICATOR_GROUPS.map((group) => (
        <div
          key={group.label}
          style={{
            background: "#111827",
            border: "1px solid #374151",
            borderRadius: 12,
            padding: 20,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: "#9ca3af" }}>
            {group.label}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {group.items.map((item) => (
              <IndicatorCard
                key={item.key}
                label={item.label}
                value={data?.indicators[item.key as keyof typeof data.indicators] ?? null}
                fmt={item.fmt}
                colorize={item.colorize}
                invert={item.invert}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
