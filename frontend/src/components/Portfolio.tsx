import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface Holding {
  ticker: string;
  market: string;
  name?: string;
  qty: number;
  avg_price: number;       // KRW
  current_price: number;   // KRW
  current_price_usd?: number; // NASDAQ만
  position_value: number;  // KRW
  unrealized_pnl: number;  // KRW
  pnl_pct: number;
  currency: "KRW" | "USD";
}

interface PortfolioData {
  cash: number;
  base_currency: string;
  fx_rate_usd: number;
  holdings: Holding[];
  totals: {
    positions_value: number;
    total_assets: number;
    unrealized_pnl: number;
    realized_pnl: number;
  };
}

function pnlColor(v: number) {
  return v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#9ca3af";
}

function fmtKrw(v: number) {
  return "₩" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function Portfolio() {
  const { data, isFetching, refetch } = useQuery<PortfolioData>({
    queryKey: ["portfolio"],
    queryFn: async () => (await api.get("/portfolio")).data,
    refetchOnWindowFocus: false,
  });

  return (
    <div style={{
      background: "#111827", border: "1px solid #374151",
      borderRadius: 12, padding: 24, color: "#f9fafb",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>포트폴리오</h3>
          {data?.fx_rate_usd && (
            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 3 }}>
              💱 USD/KRW ₩{data.fx_rate_usd.toLocaleString()} · 모든 금액 KRW 기준
            </div>
          )}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          style={{
            background: "#1f2937", border: "1px solid #374151", borderRadius: 6,
            color: "#9ca3af", padding: "4px 12px", fontSize: 12, cursor: "pointer",
          }}
        >
          {isFetching ? "갱신 중..." : "새로고침"}
        </button>
      </div>

      {data && (
        <>
          {/* Summary */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 12 }}>
            {[
              { label: "가용 현금 (KRW)", value: fmtKrw(data.cash) },
              { label: "보유 자산 (KRW)", value: fmtKrw(data.totals.positions_value) },
              { label: "총 자산 (KRW)", value: fmtKrw(data.totals.total_assets) },
            ].map((item) => (
              <div key={item.label} style={{ background: "#1f2937", borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{item.value}</div>
              </div>
            ))}
          </div>

          {/* 손익 요약 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            {[
              { label: "미실현 손익", value: data.totals.unrealized_pnl ?? 0 },
              { label: "실현 손익 (누적)", value: data.totals.realized_pnl ?? 0 },
            ].map((item) => (
              <div key={item.label} style={{ background: "#1f2937", borderRadius: 8, padding: "10px 14px" }}>
                <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontWeight: 700, fontSize: 15, color: pnlColor(item.value) }}>
                  {item.value >= 0 ? "+" : ""}{fmtKrw(item.value).replace("₩", "")}원
                </div>
              </div>
            ))}
          </div>

          {/* Holdings table */}
          {data.holdings.length === 0 ? (
            <div style={{ textAlign: "center", color: "#6b7280", padding: "24px 0", fontSize: 14 }}>
              보유 종목 없음 — 위 분석 화면에서 매수해 보세요
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #374151" }}>
                    <th style={{ padding: "6px 8px", textAlign: "left", color: "#6b7280", fontWeight: 500, whiteSpace: "nowrap" }}>종목</th>
                    <th style={{ padding: "6px 8px", textAlign: "left", color: "#6b7280", fontWeight: 500, whiteSpace: "nowrap" }}>시장</th>
                    {["수량", "평균단가(₩)", "현재가(₩)", "평가금액(₩)", "손익(₩)", "수익률"].map((h) => (
                      <th key={h} style={{ padding: "6px 8px", textAlign: "right", color: "#6b7280", fontWeight: 500, whiteSpace: "nowrap" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.holdings.map((h) => (
                    <tr key={`${h.ticker}-${h.market}`} style={{ borderBottom: "1px solid #1f2937" }}>
                      <td style={{ padding: "8px 8px", fontWeight: 600 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          {h.ticker}
                          {h.currency === "USD" && (
                            <span style={{ fontSize: 10, color: "#60a5fa" }}>USD</span>
                          )}
                        </div>
                        {h.name && (
                          <div style={{ fontSize: 11, color: "#6b7280", fontWeight: 400, marginTop: 2 }}>
                            {h.name}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "8px 8px", color: "#9ca3af", verticalAlign: "top" }}>{h.market}</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top" }}>{h.qty}</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top" }}>
                        {fmtKrw(h.avg_price)}
                      </td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top" }}>
                        {fmtKrw(h.current_price)}
                        {h.current_price_usd && (
                          <div style={{ fontSize: 10, color: "#6b7280" }}>
                            ${h.current_price_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top" }}>{fmtKrw(h.position_value)}</td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top", color: pnlColor(h.unrealized_pnl) }}>
                        {h.unrealized_pnl >= 0 ? "+" : ""}{fmtKrw(h.unrealized_pnl).replace("₩", "")}
                      </td>
                      <td style={{ padding: "8px 8px", textAlign: "right", verticalAlign: "top", color: pnlColor(h.pnl_pct) }}>
                        {h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
