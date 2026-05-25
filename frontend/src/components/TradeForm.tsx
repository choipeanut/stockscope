import { useState } from "react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  ticker: string;
  market: string;
  currentPrice?: number; // 원본 통화 (NASDAQ=USD, KOSDAQ=KRW)
}

export function TradeForm({ ticker, market, currentPrice }: Props) {
  const qc = useQueryClient();
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState("1");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // 포트폴리오에서 USD/KRW 환율 가져오기
  const { data: portData } = useQuery<{ fx_rate_usd?: number }>({
    queryKey: ["portfolio"],
    queryFn: async () => (await api.get("/portfolio")).data,
    staleTime: 30 * 60 * 1000,
  });

  const fxRate = portData?.fx_rate_usd ?? 1400;
  const isUsd = market === "NASDAQ";

  // 예상 금액 계산 (KRW 기준)
  const priceKrw = currentPrice
    ? isUsd ? currentPrice * fxRate : currentPrice
    : null;
  const estimate = priceKrw ? priceKrw * parseFloat(qty || "0") : null;

  const mutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post("/trade", {
        side,
        ticker,
        market,
        qty: parseFloat(qty),
      });
      return data;
    },
    onSuccess: (data) => {
      const priceStr = isUsd
        ? `$${data.price_native?.toLocaleString(undefined, { maximumFractionDigits: 2 })} (₩${data.price?.toLocaleString()})`
        : `₩${data.price?.toLocaleString()}`;
      const fxStr = data.fx_rate ? ` | 환율 ₩${data.fx_rate?.toLocaleString()}/USD` : "";
      setMsg({
        ok: true,
        text: side === "BUY"
          ? `✅ ${ticker} ${data.qty}주 매수 @ ${priceStr}${fxStr}`
          : `✅ ${ticker} ${data.qty}주 매도 @ ${priceStr} (실현손익: ₩${data.realized_pnl?.toLocaleString() ?? "-"})`,
      });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (e: any) => {
      const detail = e?.response?.data?.detail ?? e.message;
      setMsg({ ok: false, text: `❌ ${detail}` });
    },
  });

  return (
    <div style={{
      background: "#111827", border: "1px solid #374151",
      borderRadius: 12, padding: 20, color: "#f9fafb",
    }}>
      <h4 style={{ margin: "0 0 14px", fontSize: 15, fontWeight: 600 }}>
        모의 투자 — {ticker} ({market})
      </h4>

      {/* 환율 표시 (NASDAQ만) */}
      {isUsd && (
        <div style={{
          background: "#1f2937", borderRadius: 6, padding: "6px 10px",
          marginBottom: 10, fontSize: 12, color: "#9ca3af",
          display: "flex", justifyContent: "space-between",
        }}>
          <span>💱 USD/KRW 환율</span>
          <span style={{ color: "#f9fafb", fontWeight: 600 }}>
            ₩{fxRate.toLocaleString()}/USD
          </span>
        </div>
      )}

      {/* 현재가 표시 */}
      {currentPrice != null && (
        <div style={{
          background: "#1f2937", borderRadius: 6, padding: "6px 10px",
          marginBottom: 12, fontSize: 12, color: "#9ca3af",
          display: "flex", justifyContent: "space-between",
        }}>
          <span>현재가</span>
          <span style={{ color: "#f9fafb", fontWeight: 600 }}>
            {isUsd
              ? `$${currentPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })} ≈ ₩${Math.round(currentPrice * fxRate).toLocaleString()}`
              : `₩${currentPrice.toLocaleString()}`
            }
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {(["BUY", "SELL"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setSide(s)}
            style={{
              flex: 1, padding: "8px 0", borderRadius: 6, border: "none",
              fontWeight: 600, fontSize: 14, cursor: "pointer",
              background: side === s
                ? s === "BUY" ? "#15803d" : "#b91c1c"
                : "#1f2937",
              color: side === s ? "#fff" : "#9ca3af",
            }}
          >
            {s === "BUY" ? "매수" : "매도"}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <input
          type="number"
          value={qty}
          min="1"
          onChange={(e) => setQty(e.target.value)}
          style={{
            flex: 1, background: "#1f2937", border: "1px solid #374151",
            borderRadius: 6, color: "#f9fafb", padding: "8px 12px",
            fontSize: 15, outline: "none",
          }}
          placeholder="수량"
        />
        <span style={{ color: "#6b7280", fontSize: 13 }}>주</span>
      </div>

      {estimate !== null && estimate > 0 && (
        <div style={{ fontSize: 13, color: "#9ca3af", marginBottom: 12 }}>
          예상 {side === "BUY" ? "매수" : "매도"}금액:{" "}
          <span style={{ color: "#f9fafb", fontWeight: 600 }}>
            ₩{Math.round(estimate).toLocaleString()}
          </span>
          {isUsd && currentPrice && (
            <span style={{ color: "#6b7280", marginLeft: 6, fontSize: 11 }}>
              (${(currentPrice * parseFloat(qty || "0")).toLocaleString(undefined, { maximumFractionDigits: 2 })})
            </span>
          )}
        </div>
      )}

      <button
        onClick={() => { setMsg(null); mutation.mutate(); }}
        disabled={mutation.isPending || !qty || parseFloat(qty) <= 0}
        style={{
          width: "100%", padding: "10px 0", borderRadius: 6, border: "none",
          fontWeight: 700, fontSize: 14, cursor: mutation.isPending ? "not-allowed" : "pointer",
          background: side === "BUY" ? "#16a34a" : "#dc2626",
          color: "#fff", opacity: mutation.isPending ? 0.7 : 1,
        }}
      >
        {mutation.isPending ? "처리 중..." : side === "BUY" ? "매수 실행" : "매도 실행"}
      </button>

      {msg && (
        <div style={{
          marginTop: 10, padding: "8px 12px", borderRadius: 6,
          background: msg.ok ? "#052e16" : "#2d0c0c",
          color: msg.ok ? "#86efac" : "#fca5a5", fontSize: 13,
        }}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
