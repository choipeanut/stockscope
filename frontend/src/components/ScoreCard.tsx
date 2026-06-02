import type { AnalyzeResponse, MarketSentimentDetail } from "../api/client";
import { FreshnessBadge } from "./FreshnessBadge";

const FACTOR_LABELS: Record<string, string> = {
  fundamental:      "펀더멘털",
  valuation:        "밸류에이션",
  supply_demand:    "수급",
  momentum:         "모멘텀",
  macro:            "거시환경",
  risk:             "리스크",
  market_sentiment: "시장 환경",
  analyst:          "애널리스트",
  insider:          "내부자거래",
  options:          "옵션심리",
};

const FACTOR_WEIGHTS: Record<string, number> = {
  fundamental:      22,
  valuation:        15,
  supply_demand:    11,
  momentum:         11,
  macro:             8,
  risk:              8,
  market_sentiment:  7,
  analyst:           8,
  insider:           6,
  options:           4,
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
          <div style={{
            width: `${score}%`, height: "100%",
            background: scoreColor(score), borderRadius: 4,
            transition: "width 0.4s ease",
          }} />
        )}
      </div>
    </div>
  );
}

function MarketSentimentCard({ detail }: { detail: MarketSentimentDetail }) {
  const trend = detail.market_trend ?? "neutral";
  const trendColor =
    trend === "bullish" ? "#22c55e" : trend === "bearish" ? "#ef4444" : "#6b7280";
  const trendBg =
    trend === "bullish" ? "#052e16" : trend === "bearish" ? "#2d0a0a" : "#1a1f2e";
  const trendLabel =
    trend === "bullish" ? "강세 📈" : trend === "bearish" ? "약세 📉" : "중립 ➖";
  const confidenceLabel =
    detail.confidence === "high" ? "높음" : detail.confidence === "medium" ? "보통" : "낮음";

  return (
    <div style={{
      background: detail.available ? trendBg : "#1a1f2e",
      border: `1px solid ${detail.available ? trendColor : "#374151"}`,
      borderRadius: 10, padding: "14px 16px", marginBottom: 20,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e7eb" }}>
          🌐 전체 시장 환경
        </span>
        {detail.available ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "#9ca3af", background: "#1f2937", borderRadius: 4, padding: "2px 6px" }}>
              신뢰도 {confidenceLabel}
            </span>
            <span style={{
              fontSize: 13, fontWeight: 700, color: trendColor,
              background: `${trendColor}22`, borderRadius: 6,
              padding: "3px 10px", border: `1px solid ${trendColor}44`,
            }}>
              {trendLabel}
            </span>
          </div>
        ) : (
          <span style={{ fontSize: 12, color: "#6b7280" }}>
            {detail.reason?.includes("ANTHROPIC") ? "ANTHROPIC_API_KEY 필요" : "키 필요"}
          </span>
        )}
      </div>

      {detail.available && detail.market_score !== null && (
        <div style={{
          display: "flex", alignItems: "center", gap: 12, marginBottom: 10,
          background: "#0f172a", borderRadius: 8, padding: "10px 14px",
        }}>
          <div style={{ textAlign: "center", minWidth: 60 }}>
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>시장 점수</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: trendColor }}>
              {detail.market_score}
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ background: "#1f2937", borderRadius: 4, height: 8 }}>
              <div style={{
                width: `${detail.market_score}%`, height: "100%",
                background: trendColor, borderRadius: 4,
                transition: "width 0.4s ease",
              }} />
            </div>
            {detail.summary && (
              <div style={{ fontSize: 12, color: "#d1d5db", marginTop: 8, lineHeight: 1.5 }}>
                {detail.summary}
              </div>
            )}
          </div>
        </div>
      )}

      {detail.available && (detail.key_themes?.length ?? 0) > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {detail.key_themes.map((theme, i) => (
            <span key={i} style={{
              fontSize: 11, color: trendColor,
              background: `${trendColor}15`,
              border: `1px solid ${trendColor}33`,
              borderRadius: 4, padding: "2px 8px",
            }}>
              {theme}
            </span>
          ))}
        </div>
      )}

      {!detail.available && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          {detail.reason?.includes("ANTHROPIC")
            ? "ANTHROPIC_API_KEY(Claude) 설정 시 글로벌 시장 환경이 분석됩니다."
            : "NEWSAPI_KEY + ANTHROPIC_API_KEY 설정 시 글로벌 시장 환경이 반영됩니다."}
        </div>
      )}
    </div>
  );
}

/** 백엔드 unavailable reason → 사용자에게 정확한 안내.
 * 뉴스 감성/시장 감성은 NewsAPI(기사 수집)가 아니라 Claude(분석)로 만들어진다 —
 * 그래서 진짜 필요한 키는 보통 ANTHROPIC_API_KEY다. */
function sentimentHint(reason?: string): string {
  const r = reason ?? "";
  if (r.includes("ANTHROPIC")) return "ANTHROPIC_API_KEY(Claude) 설정 시 뉴스 감성 분석이 켜집니다.";
  if (r.includes("NEWSAPI") || r.includes("no global macro news"))
    return "NEWSAPI_KEY 설정 시 거시 환경 뉴스가 반영됩니다.";
  if (r.includes("no stock-specific") || r.includes("no items"))
    return "이 종목의 최근 뉴스·공시가 없어 감성 분석을 건너뜁니다.";
  return r ? `감성 분석 미사용: ${r}` : "뉴스 감성 분석을 사용할 수 없습니다.";
}

interface Props {
  data: AnalyzeResponse;
}

export function ScoreCard({ data }: Props) {
  const {
    composite, composite_raw, sentiment_delta, sentiment,
    factors, unavailable, renormalized, as_of, ticker, market, name, notice,
    market_sentiment_detail,
  } = data;

  const s = sentiment?.sentiment ?? "neutral";
  const sentimentColor = s === "positive" ? "#22c55e" : s === "negative" ? "#ef4444" : "#6b7280";
  const sentimentBg = s === "positive" ? "#052e16" : s === "negative" ? "#2d0a0a" : "#1a1f2e";
  const sentimentLabel = s === "positive" ? "긍정적 📈" : s === "negative" ? "부정적 📉" : "중립 ➖";
  const deltaStr = (sentiment_delta ?? 0) > 0
    ? `+${sentiment_delta}점`
    : (sentiment_delta ?? 0) < 0
    ? `${sentiment_delta}점`
    : "±0점";
  const hasSentiment = sentiment?.available === true;

  return (
    <div style={{
      background: "#111827", border: "1px solid #374151",
      borderRadius: 12, padding: 24, color: "#f9fafb",
      maxWidth: 480, width: "100%",
    }}>
      {/* ── 헤더: 종목명 + 타임스탬프 ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          {name && (
            <div style={{ fontSize: 18, fontWeight: 700, color: "#f9fafb", marginBottom: 2 }}>
              {name}
            </div>
          )}
          <h2 style={{ margin: 0, fontSize: name ? 14 : 22, fontWeight: name ? 400 : 700, color: name ? "#9ca3af" : "#f9fafb" }}>
            {ticker}{" "}
            <span style={{ fontSize: name ? 13 : 14, color: "#6b7280", fontWeight: 400 }}>{market}</span>
          </h2>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
            <span>{new Date(as_of).toLocaleString("ko-KR")}</span>
            <FreshnessBadge asOf={as_of} staleAfterMinutes={30} />
          </div>
        </div>

        {/* 복합 점수 원형 */}
        {composite !== null && (
          <div style={{
            width: 76, height: 76, borderRadius: "50%",
            border: `4px solid ${scoreColor(composite)}`,
            display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column",
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 24, fontWeight: 800, color: scoreColor(composite), lineHeight: 1 }}>
              {composite.toFixed(0)}
            </span>
            <span style={{ fontSize: 10, color: "#9ca3af" }}>/ 100</span>
          </div>
        )}
      </div>

      {/* ── 뉴스 감성 점수 카드 ── */}
      <div style={{
        background: hasSentiment ? sentimentBg : "#1a1f2e",
        border: `1px solid ${hasSentiment ? sentimentColor : "#374151"}`,
        borderRadius: 10, padding: "14px 16px", marginBottom: 20,
      }}>
        {/* 헤더 행 */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e7eb" }}>
            📰 뉴스 감성 점수
          </span>
          {hasSentiment ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{
                fontSize: 11, color: "#9ca3af",
                background: "#1f2937", borderRadius: 4, padding: "2px 6px",
              }}>
                신뢰도 {sentiment.confidence === "high" ? "높음" : sentiment.confidence === "medium" ? "보통" : "낮음"}
              </span>
              <span style={{
                fontSize: 13, fontWeight: 700, color: sentimentColor,
                background: `${sentimentColor}22`, borderRadius: 6,
                padding: "3px 10px", border: `1px solid ${sentimentColor}44`,
              }}>
                {sentimentLabel}
              </span>
            </div>
          ) : (
            <span style={{ fontSize: 12, color: "#6b7280" }}>분석 중...</span>
          )}
        </div>

        {/* 점수 보정 표시 */}
        {hasSentiment && (
          <div style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 10,
            background: "#0f172a", borderRadius: 8, padding: "10px 14px",
          }}>
            <div style={{ textAlign: "center", flex: 1 }}>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>기본 점수</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "#d1d5db" }}>
                {composite_raw?.toFixed(0) ?? "--"}
              </div>
            </div>
            <div style={{ fontSize: 22, color: "#374151" }}>→</div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>뉴스 보정</div>
              <div style={{
                fontSize: 18, fontWeight: 700,
                color: (sentiment_delta ?? 0) > 0 ? "#22c55e" : (sentiment_delta ?? 0) < 0 ? "#ef4444" : "#6b7280",
              }}>
                {deltaStr}
              </div>
            </div>
            <div style={{ fontSize: 22, color: "#374151" }}>→</div>
            <div style={{ textAlign: "center", flex: 1 }}>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 2 }}>최종 점수</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: composite !== null ? scoreColor(composite) : "#6b7280" }}>
                {composite?.toFixed(0) ?? "--"}
              </div>
            </div>
          </div>
        )}

        {/* 요약 */}
        {hasSentiment && sentiment.summary ? (
          <div style={{ fontSize: 12, color: "#d1d5db", marginBottom: 8, lineHeight: 1.5 }}>
            {sentiment.summary}
          </div>
        ) : !hasSentiment ? (
          <div style={{ fontSize: 12, color: "#6b7280" }}>
            {sentimentHint(sentiment?.reason)}
          </div>
        ) : null}

        {/* 핵심 시그널 태그 */}
        {hasSentiment && (sentiment.key_signals?.length ?? 0) > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {sentiment.key_signals.map((sig, i) => (
              <span key={i} style={{
                fontSize: 11, color: sentimentColor,
                background: `${sentimentColor}15`,
                border: `1px solid ${sentimentColor}33`,
                borderRadius: 4, padding: "2px 8px",
              }}>
                {sig}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ── 전체 시장 환경 카드 ── */}
      {market_sentiment_detail && (
        <MarketSentimentCard detail={market_sentiment_detail} />
      )}

      {/* ── 팩터 재정규화 알림 ── */}
      {renormalized && (
        <div style={{
          background: "#1f2937", border: "1px solid #374151",
          borderRadius: 6, padding: "8px 12px", marginBottom: 16,
          fontSize: 12, color: "#9ca3af",
        }}>
          일부 팩터 데이터가 없어 가중치를 재정규화했습니다.
        </div>
      )}

      {/* ── 팩터 바 ── */}
      {Object.entries(factors).map(([key, val]) => (
        <FactorBar
          key={key}
          name={key}
          score={val}
          weight={FACTOR_WEIGHTS[key] ?? 0}
          unavailable={unavailable.includes(key)}
        />
      ))}

      {/* ── 면책 ── */}
      <div style={{
        marginTop: 20, padding: "10px 12px",
        background: "#1f2937", borderRadius: 6,
        fontSize: 11, color: "#6b7280",
        borderLeft: "3px solid #374151",
      }}>
        ⚠️ {notice}
      </div>
    </div>
  );
}
