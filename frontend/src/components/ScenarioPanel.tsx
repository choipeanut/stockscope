interface Scenario {
  stance: "bull" | "bear" | "neutral";
  probability_hint: "low" | "medium" | "high";
  reasons: string[];
  watch_conditions: string[];
}

const STANCE_CONFIG = {
  bull: { label: "상승 (Bull)", bg: "#052e16", border: "#16a34a", icon: "▲", color: "#22c55e" },
  bear: { label: "하락 (Bear)", bg: "#2d0c0c", border: "#dc2626", icon: "▼", color: "#ef4444" },
  neutral: { label: "중립 (Neutral)", bg: "#1c1917", border: "#d97706", icon: "◆", color: "#f59e0b" },
};

const PROB_LABEL = { low: "낮음", medium: "보통", high: "높음" };

export function ScenarioPanel({ scenarios }: { scenarios: Scenario[] }) {
  if (!scenarios || scenarios.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, width: "100%" }}>
      <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#f9fafb" }}>
        시나리오 분석
      </h3>
      {scenarios.map((s) => {
        const cfg = STANCE_CONFIG[s.stance];
        return (
          <div
            key={s.stance}
            style={{
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
              borderRadius: 10,
              padding: "14px 16px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 10,
              }}
            >
              <span style={{ fontWeight: 700, color: cfg.color, fontSize: 15 }}>
                {cfg.icon} {cfg.label}
              </span>
              <span
                style={{
                  fontSize: 12,
                  background: "rgba(255,255,255,0.08)",
                  borderRadius: 4,
                  padding: "2px 8px",
                  color: "#9ca3af",
                }}
              >
                확률: {PROB_LABEL[s.probability_hint]}
              </span>
            </div>

            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 4 }}>근거</div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {s.reasons.map((r, i) => (
                  <li key={i} style={{ fontSize: 13, color: "#e5e7eb", marginBottom: 2 }}>
                    {r}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 4 }}>모니터링 포인트</div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {s.watch_conditions.map((w, i) => (
                  <li key={i} style={{ fontSize: 12, color: "#6b7280", marginBottom: 2 }}>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        );
      })}
    </div>
  );
}
