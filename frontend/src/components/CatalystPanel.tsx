import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchCatalystRun,
  fetchCatalystScoreboard,
  fetchCatalystHistory,
  type CatalystPick,
  type PredictionRecord,
} from "../api/client";

type Market = "KR" | "KOSPI" | "KOSDAQ" | "NASDAQ";

interface Props {
  onDrillDown?: (ticker: string, market: string) => void;
}

const DIR_COLOR: Record<string, string> = {
  bullish: "#22c55e",
  bearish: "#ef4444",
  neutral: "#9ca3af",
};

const TYPE_LABEL: Record<string, string> = {
  guidance_up: "가이던스↑",
  guidance_down: "가이던스↓",
  contract_win: "수주",
  capacity_expansion: "증설",
  earnings_beat: "실적상회",
  earnings_miss: "실적하회",
  buyback: "자사주",
  dividend: "배당",
  equity_dilution: "유상증자",
  litigation: "소송",
  mna: "M&A",
  none: "—",
};

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function CatalystPanel({ onDrillDown }: Props) {
  const [market, setMarket] = useState<Market>("KR");
  const [horizon, setHorizon] = useState(21);
  const [triggered, setTriggered] = useState(false);

  const run = useQuery({
    queryKey: ["catalyst-run", market, horizon],
    queryFn: () => fetchCatalystRun(market, horizon, 10),
    enabled: triggered,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 8_000 : false),
  });

  const board = useQuery({
    queryKey: ["catalyst-scoreboard"],
    queryFn: () => fetchCatalystScoreboard("catalyst"),
    refetchOnWindowFocus: false,
  });

  const history = useQuery({
    queryKey: ["catalyst-history"],
    queryFn: () => fetchCatalystHistory("catalyst", 60),
    refetchOnWindowFocus: false,
  });

  const picks: CatalystPick[] =
    run.data?.status === "ok" ? run.data.picks ?? [] : [];
  const scored: PredictionRecord[] =
    (history.data?.predictions ?? []).filter((p) => p.scored_at);

  return (
    <div style={{ color: "#f9fafb" }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>
          🎯 촉매 전략 (이벤트 드리븐)
        </h2>
        <p style={{ color: "#9ca3af", fontSize: 13, marginTop: 6, lineHeight: 1.6 }}>
          공시·실적을 <b>Claude가 읽어</b> 촉매(가이던스·수주·증설·유상증자 등)를 분류하고,
          <b> 실적 YoY 서프라이즈</b>와 결합해 향후 {horizon}거래일을 베팅합니다.
          모든 픽은 <b>사전 등록된 가설(thesis)</b>로 박제되어, 아래 성과표에서
          <b> 미래 실현 수익으로 정직하게 검증</b>됩니다 (지수 대비 초과수익 기준).
        </p>
      </div>

      {/* 누적 성과표 — 이게 핵심 */}
      <div style={{
        display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16,
        padding: 14, background: "#111827", borderRadius: 10, border: "1px solid #1f2937",
      }}>
        <ScoreStat label="채점된 픽" value={board.data ? String(board.data.n_scored) : "—"} />
        <ScoreStat
          label="적중률 (지수 초과)"
          value={board.data?.hit_rate != null ? `${(board.data.hit_rate * 100).toFixed(0)}%` : "—"}
          hint="50% 미만이면 전략에 우위 없음"
        />
        <ScoreStat label="평균 초과수익" value={pct(board.data?.avg_excess)}
          color={(board.data?.avg_excess ?? 0) >= 0 ? "#22c55e" : "#ef4444"} />
        <ScoreStat label="평균 종목수익" value={pct(board.data?.avg_stock)} />
        <ScoreStat label="평균 지수수익" value={pct(board.data?.avg_bench)} />
      </div>

      {/* 컨트롤 */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
        <select value={market} onChange={(e) => setMarket(e.target.value as Market)}
          style={SELECT}>
          <option value="KR">한국 (코스피+코스닥)</option>
          <option value="KOSPI">KOSPI</option>
          <option value="KOSDAQ">KOSDAQ</option>
          <option value="NASDAQ">NASDAQ</option>
        </select>
        <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}
          style={SELECT}>
          <option value={21}>1개월 (21일)</option>
          <option value={63}>3개월 (63일)</option>
        </select>
        <button onClick={() => setTriggered(true)} disabled={run.data?.status === "running"}
          style={{
            ...BTN, opacity: run.data?.status === "running" ? 0.6 : 1,
            cursor: run.data?.status === "running" ? "default" : "pointer",
          }}>
          {run.data?.status === "running" ? "분석 중…" : "촉매 분석 실행"}
        </button>
      </div>

      {run.data?.status === "running" && (
        <p style={{ color: "#9ca3af", fontSize: 13 }}>
          공시를 Claude가 읽는 중… 1~2분 소요. 완료 시 자동 표시됩니다.
        </p>
      )}
      {run.error && (
        <p style={{ color: "#ef4444", fontSize: 13 }}>{(run.error as Error).message}</p>
      )}

      {/* 이번 배치 픽 */}
      {picks.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            오늘의 촉매 픽 — 박제 완료 ({run.data?.n_stored ?? picks.length}건 저장,
            만기 채점 {run.data?.n_scored_due ?? 0}건)
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "#9ca3af", textAlign: "left" }}>
                <th style={TH}>#</th><th style={TH}>종목</th><th style={TH}>점수</th>
                <th style={TH}>촉매</th><th style={TH}>근거 (사전 등록)</th>
              </tr>
            </thead>
            <tbody>
              {picks.map((p) => (
                <tr key={`${p.ticker}-${p.market}`}
                  onClick={() => onDrillDown?.(p.ticker, p.market)}
                  style={{ borderTop: "1px solid #1f2937", cursor: "pointer" }}>
                  <td style={TD}>{p.rank}</td>
                  <td style={TD}>
                    <b>{p.name || p.ticker}</b>
                    <span style={{ color: "#6b7280", marginLeft: 6, fontSize: 11 }}>{p.ticker}</span>
                  </td>
                  <td style={{ ...TD, fontWeight: 700 }}>{p.score.toFixed(0)}</td>
                  <td style={TD}>
                    <span style={{ color: DIR_COLOR[p.direction ?? "neutral"] }}>
                      {TYPE_LABEL[p.catalyst_type ?? "none"] ?? p.catalyst_type}
                    </span>
                  </td>
                  <td style={{ ...TD, color: "#d1d5db" }}>{p.thesis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 검증된 과거 픽 (실현 결과) */}
      {scored.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            검증된 과거 픽 — 예측대로 됐나?
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "#9ca3af", textAlign: "left" }}>
                <th style={TH}>박제일</th><th style={TH}>종목</th><th style={TH}>근거</th>
                <th style={TH}>종목</th><th style={TH}>지수</th>
                <th style={TH}>초과</th><th style={TH}>결과</th>
              </tr>
            </thead>
            <tbody>
              {scored.map((p) => (
                <tr key={p.id} style={{ borderTop: "1px solid #1f2937" }}>
                  <td style={{ ...TD, color: "#6b7280" }}>{p.created_at.slice(0, 10)}</td>
                  <td style={TD}><b>{p.name || p.ticker}</b></td>
                  <td style={{ ...TD, color: "#9ca3af", maxWidth: 240 }}>{p.thesis}</td>
                  <td style={TD}>{pct(p.stock_return)}</td>
                  <td style={{ ...TD, color: "#6b7280" }}>{pct(p.bench_return)}</td>
                  <td style={{ ...TD, color: (p.excess_return ?? 0) >= 0 ? "#22c55e" : "#ef4444" }}>
                    {pct(p.excess_return)}
                  </td>
                  <td style={TD}>{p.hit === 1 ? "✅ 적중" : "❌ 빗나감"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {run.data?.disclaimer && (
        <p style={{ color: "#6b7280", fontSize: 11, marginTop: 16 }}>⚠️ {run.data.disclaimer}</p>
      )}
    </div>
  );
}

function ScoreStat({ label, value, hint, color }: {
  label: string; value: string; hint?: string; color?: string;
}) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 11, color: "#9ca3af" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: color ?? "#f9fafb" }}>{value}</div>
      {hint && <div style={{ fontSize: 10, color: "#6b7280" }}>{hint}</div>}
    </div>
  );
}

const SELECT: React.CSSProperties = {
  background: "#1f2937", color: "#f9fafb", border: "1px solid #374151",
  borderRadius: 6, padding: "6px 10px", fontSize: 13,
};
const BTN: React.CSSProperties = {
  background: "#2563eb", color: "#fff", border: "none", borderRadius: 6,
  padding: "7px 16px", fontSize: 13, fontWeight: 600,
};
const TH: React.CSSProperties = { padding: "6px 8px", fontWeight: 600 };
const TD: React.CSSProperties = { padding: "7px 8px" };
