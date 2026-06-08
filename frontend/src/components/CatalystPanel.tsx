import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchCatalystLoopRun,
  fetchCatalystScoreboard,
  fetchCatalystHistory,
  fetchCatalystWatchlist,
  addCatalystWatchlist,
  removeCatalystWatchlist,
  fetchCatalystLessons,
  type CatalystPick,
  type PredictionRecord,
} from "../api/client";

type Market = "KOSPI" | "KOSDAQ" | "NASDAQ";

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
  const qc = useQueryClient();
  const [horizon, setHorizon] = useState(21);
  const [triggered, setTriggered] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newMarket, setNewMarket] = useState<Market>("KOSPI");
  const [adding, setAdding] = useState(false);

  const watchlist = useQuery({
    queryKey: ["catalyst-watchlist"],
    queryFn: fetchCatalystWatchlist,
    refetchOnWindowFocus: false,
  });

  const run = useQuery({
    queryKey: ["catalyst-loop", horizon],
    queryFn: () => fetchCatalystLoopRun(horizon),
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

  const lessons = useQuery({
    queryKey: ["catalyst-lessons"],
    queryFn: () => fetchCatalystLessons(50),
    refetchOnWindowFocus: false,
  });

  const items = watchlist.data?.watchlist ?? [];
  const picks: CatalystPick[] =
    run.data?.status === "ok" ? run.data.picks ?? [] : [];
  const allPreds = history.data?.predictions ?? [];
  const pending: PredictionRecord[] = allPreds
    .filter((p) => !p.scored_at)
    .sort((a, b) => (a.due_at < b.due_at ? -1 : 1));
  const scored: PredictionRecord[] = allPreds.filter((p) => p.scored_at);

  // 루프가 끝나면 DB 기반 목록(추적중/과거픽/성과/교훈)을 새로고침
  useEffect(() => {
    if (run.data?.status === "ok") {
      qc.invalidateQueries({ queryKey: ["catalyst-history"] });
      qc.invalidateQueries({ queryKey: ["catalyst-scoreboard"] });
      qc.invalidateQueries({ queryKey: ["catalyst-lessons"] });
    }
  }, [run.data?.status, run.data?.as_of, qc]);

  function dday(dueAt: string): string {
    const ms = new Date(dueAt).getTime() - Date.now();
    const d = Math.ceil(ms / 86_400_000);
    return d > 0 ? `D-${d}` : d === 0 ? "D-day" : `만기 +${-d}일 (채점 대기)`;
  }

  async function handleAdd() {
    const t = newTicker.trim();
    if (!t) return;
    setAdding(true);
    try {
      await addCatalystWatchlist(t, newMarket);
      setNewTicker("");
      await qc.invalidateQueries({ queryKey: ["catalyst-watchlist"] });
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(id: number) {
    await removeCatalystWatchlist(id);
    await qc.invalidateQueries({ queryKey: ["catalyst-watchlist"] });
  }

  const running = run.data?.status === "running";

  return (
    <div style={{ color: "#f9fafb" }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>
          🎯 촉매 전략 — 자기개선 루프
        </h2>
        <p style={{ color: "#9ca3af", fontSize: 13, marginTop: 6, lineHeight: 1.6 }}>
          정해둔 종목을 매 사이클 <b>예측 → 만기 채점 → 왜 맞았나/틀렸나 사후분석 →
          교훈 추출</b>하고, 그 교훈을 <b>다음 예측 프롬프트에 주입</b>해 스스로 교정합니다.
          모든 픽은 사전 등록 가설로 박제되어 아래 성과표에서 <b>지수 대비 초과수익</b>으로
          정직하게 검증됩니다.
        </p>
      </div>

      {/* 누적 성과표 */}
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
        <ScoreStat label="누적 교훈" value={lessons.data ? String(lessons.data.count) : "—"} />
      </div>

      {/* 워치리스트 관리 */}
      <div style={{
        padding: 14, background: "#0b1220", borderRadius: 10,
        border: "1px solid #1f2937", marginBottom: 14,
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>
          추적 종목 ({items.length})
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          {items.length === 0 && (
            <span style={{ color: "#6b7280", fontSize: 13 }}>
              추적할 종목을 추가하세요 (예: 005930 / KOSPI).
            </span>
          )}
          {items.map((w) => (
            <span key={w.id} style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              background: "#1f2937", borderRadius: 6, padding: "4px 8px", fontSize: 12,
            }}>
              <b>{w.name || w.ticker}</b>
              <span style={{ color: "#6b7280" }}>{w.ticker}·{w.market}</span>
              <button onClick={() => handleRemove(w.id)}
                style={{
                  background: "none", border: "none", color: "#ef4444",
                  cursor: "pointer", fontSize: 14, lineHeight: 1, padding: 0,
                }} title="삭제">×</button>
            </span>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input value={newTicker} onChange={(e) => setNewTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            placeholder="종목코드 (예: 005930, AAPL)"
            style={{
              background: "#1f2937", color: "#f9fafb", border: "1px solid #374151",
              borderRadius: 6, padding: "6px 10px", fontSize: 13, width: 200,
            }} />
          <select value={newMarket} onChange={(e) => setNewMarket(e.target.value as Market)}
            style={SELECT}>
            <option value="KOSPI">KOSPI</option>
            <option value="KOSDAQ">KOSDAQ</option>
            <option value="NASDAQ">NASDAQ</option>
          </select>
          <button onClick={handleAdd} disabled={adding || !newTicker.trim()}
            style={{ ...BTN, background: "#374151", opacity: adding ? 0.6 : 1 }}>
            {adding ? "추가 중…" : "+ 추가"}
          </button>
        </div>
      </div>

      {/* 컨트롤 */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
        <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}
          style={SELECT}>
          <option value={7}>1주일 (7일)</option>
          <option value={21}>1개월 (21일)</option>
          <option value={63}>3개월 (63일)</option>
        </select>
        <button onClick={() => setTriggered(true)} disabled={running || items.length === 0}
          style={{
            ...BTN, opacity: running || items.length === 0 ? 0.6 : 1,
            cursor: running || items.length === 0 ? "default" : "pointer",
          }}>
          {running ? "루프 실행 중…" : "루프 실행 (채점·사후분석·재예측)"}
        </button>
      </div>

      {running && (
        <p style={{ color: "#9ca3af", fontSize: 13 }}>
          만기 픽 채점 → 사후분석 → 교훈 반영 재예측 중… 1~2분 소요. 완료 시 자동 표시됩니다.
        </p>
      )}
      {run.error && (
        <p style={{ color: "#ef4444", fontSize: 13 }}>{(run.error as Error).message}</p>
      )}

      {/* 이번 사이클 픽 */}
      {picks.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            이번 사이클 픽 — 박제 {run.data?.n_stored ?? picks.length}건 · 만기채점{" "}
            {run.data?.n_scored_due ?? 0}건 · 사후분석 {run.data?.n_reflected ?? 0}건 · 신규교훈{" "}
            {run.data?.n_lessons ?? 0}개
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "#9ca3af", textAlign: "left" }}>
                <th style={TH}>#</th><th style={TH}>종목</th><th style={TH}>점수</th>
                <th style={TH}>촉매</th><th style={TH}>교훈반영</th>
                <th style={TH}>근거 (사전 등록)</th>
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
                  <td style={{ ...TD, color: "#6b7280" }}>
                    {p.lessons_used ? `${p.lessons_used}개` : "—"}
                  </td>
                  <td style={{ ...TD, color: "#d1d5db" }}>{p.thesis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 추적 중 (만기 대기) — DB 기반이라 새로고침/재배포에도 유지 */}
      {pending.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            ⏳ 추적 중 — 만기 대기 ({pending.length}건)
          </h3>
          <p style={{ color: "#6b7280", fontSize: 12, margin: "0 0 8px" }}>
            박제된 예측은 만기일까지 보존됩니다. 만기 이후 <b>루프를 다시 실행</b>하면 채점돼요.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "#9ca3af", textAlign: "left" }}>
                <th style={TH}>박제일</th><th style={TH}>종목</th><th style={TH}>점수</th>
                <th style={TH}>만기일</th><th style={TH}>남은기간</th>
                <th style={TH}>근거 (사전 등록)</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p) => (
                <tr key={p.id}
                  onClick={() => onDrillDown?.(p.ticker, p.market)}
                  style={{ borderTop: "1px solid #1f2937", cursor: "pointer" }}>
                  <td style={{ ...TD, color: "#6b7280" }}>{p.created_at.slice(0, 10)}</td>
                  <td style={TD}>
                    <b>{p.name || p.ticker}</b>
                    <span style={{ color: "#6b7280", marginLeft: 6, fontSize: 11 }}>{p.ticker}</span>
                  </td>
                  <td style={{ ...TD, fontWeight: 700 }}>{p.score?.toFixed(0) ?? "—"}</td>
                  <td style={{ ...TD, color: "#9ca3af" }}>{p.due_at.slice(0, 10)}</td>
                  <td style={{
                    ...TD,
                    color: new Date(p.due_at).getTime() <= Date.now() ? "#f59e0b" : "#9ca3af",
                  }}>{dday(p.due_at)}</td>
                  <td style={{ ...TD, color: "#d1d5db", maxWidth: 320 }}>{p.thesis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 검증된 과거 픽 + 사후분석 */}
      {scored.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            검증된 과거 픽 — 예측대로 됐나? (왜 맞았나/틀렸나)
          </h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "#9ca3af", textAlign: "left" }}>
                <th style={TH}>박제일</th><th style={TH}>종목</th>
                <th style={TH}>초과</th><th style={TH}>결과</th>
                <th style={TH}>사후분석</th>
              </tr>
            </thead>
            <tbody>
              {scored.map((p) => (
                <tr key={p.id} style={{ borderTop: "1px solid #1f2937", verticalAlign: "top" }}>
                  <td style={{ ...TD, color: "#6b7280" }}>{p.created_at.slice(0, 10)}</td>
                  <td style={TD}><b>{p.name || p.ticker}</b></td>
                  <td style={{ ...TD, color: (p.excess_return ?? 0) >= 0 ? "#22c55e" : "#ef4444" }}>
                    {pct(p.excess_return)}
                  </td>
                  <td style={TD}>{p.hit === 1 ? "✅ 적중" : "❌ 빗나감"}</td>
                  <td style={{ ...TD, color: "#9ca3af", maxWidth: 360, lineHeight: 1.5 }}>
                    {p.postmortem || <span style={{ color: "#4b5563" }}>분석 대기</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 누적 교훈 */}
      {(lessons.data?.lessons.length ?? 0) > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "8px 0" }}>
            🧠 누적 교훈 — 루프가 배운 것
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {lessons.data!.lessons.map((l) => (
              <div key={l.id} style={{
                display: "flex", gap: 8, alignItems: "baseline", fontSize: 13,
                padding: "6px 10px", background: "#111827", borderRadius: 6,
                border: "1px solid #1f2937",
              }}>
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
                  background: l.scope === "global" ? "#1e3a8a" : "#374151",
                  color: "#e5e7eb", whiteSpace: "nowrap",
                }}>
                  {l.scope === "global" ? "전역" : `${l.ticker ?? ""}`}
                </span>
                <span style={{ color: "#d1d5db" }}>{l.lesson}</span>
                {l.catalyst_type && (
                  <span style={{ color: "#6b7280", fontSize: 11 }}>
                    ({TYPE_LABEL[l.catalyst_type] ?? l.catalyst_type})
                  </span>
                )}
              </div>
            ))}
          </div>
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
