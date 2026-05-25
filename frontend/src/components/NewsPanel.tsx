import { useQuery } from "@tanstack/react-query";
import { fetchNews, type NewsItem } from "../api/client";

interface Props {
  ticker: string;
  market: string;
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return "";
  const date = new Date(
    dateStr.length === 8
      ? `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
      : dateStr,
  );
  if (isNaN(date.getTime())) return dateStr;
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}일 전`;
  return date.toLocaleDateString("ko-KR");
}

function NewsCard({ item }: { item: NewsItem }) {
  const isDisclosure = item.type === "disclosure";
  const isMacro = item.type === "macro_news";
  const borderColor = isDisclosure ? "#f59e0b" : isMacro ? "#a78bfa" : "#3b82f6";
  const badgeBg = isDisclosure ? "#92400e33" : isMacro ? "#4c1d9533" : "#1e3a5f";
  const badgeColor = isDisclosure ? "#fbbf24" : isMacro ? "#c4b5fd" : "#93c5fd";
  const badgeLabel = isDisclosure ? "📋 공시" : isMacro ? "🌐 거시" : "📰 뉴스";

  return (
    <a
      href={item.url || "#"}
      target="_blank"
      rel="noopener noreferrer"
      style={{ textDecoration: "none", color: "inherit" }}
    >
      <div
        style={{
          background: "#1f2937",
          borderRadius: 8,
          padding: "12px 14px",
          marginBottom: 8,
          borderLeft: `3px solid ${borderColor}`,
          cursor: "pointer",
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = "#27374d")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "#1f2937")}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
          <span
            style={{
              fontSize: 11,
              padding: "1px 6px",
              borderRadius: 3,
              background: badgeBg,
              color: badgeColor,
              whiteSpace: "nowrap",
            }}
          >
            {badgeLabel}
          </span>
          <span style={{ fontSize: 11, color: "#6b7280", whiteSpace: "nowrap" }}>
            {item.source && `${item.source} · `}{timeAgo(item.published)}
          </span>
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#e5e7eb", lineHeight: 1.4, marginBottom: 4 }}>
          {item.title}
        </div>
        {item.summary && (
          <div style={{ fontSize: 12, color: "#9ca3af", lineHeight: 1.4 }}>
            {item.summary}
          </div>
        )}
      </div>
    </a>
  );
}

export function NewsPanel({ ticker, market }: Props) {
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ["news", ticker, market],
    queryFn: () => fetchNews(ticker, market, 10),
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const stockItems = [...(data?.disclosures ?? []), ...(data?.news ?? [])];
  const macroItems = data?.macro_news ?? [];
  const hasAny = stockItems.length > 0 || macroItems.length > 0;

  return (
    <div
      style={{
        background: "#111827",
        border: "1px solid #374151",
        borderRadius: 12,
        padding: 20,
        color: "#f9fafb",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h4 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
          📰 뉴스 &amp; 공시 — {ticker}
        </h4>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {isFetching && <span style={{ fontSize: 12, color: "#6b7280" }}>로딩 중...</span>}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            style={{
              background: "#1f2937", border: "1px solid #374151", borderRadius: 6,
              color: "#9ca3af", padding: "4px 10px", fontSize: 12, cursor: "pointer",
            }}
          >
            새로고침
          </button>
        </div>
      </div>

      {error && (
        <div style={{ fontSize: 13, color: "#ef4444", padding: "8px 0" }}>
          뉴스를 불러올 수 없습니다.
        </div>
      )}

      {!isFetching && !hasAny && !error && (
        <div style={{ fontSize: 13, color: "#6b7280", textAlign: "center", padding: "16px 0" }}>
          최근 뉴스/공시가 없습니다.
        </div>
      )}

      {/* 종목 뉴스 & 공시 */}
      {stockItems.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8, fontWeight: 600 }}>
            종목 직접 뉴스 / 공시
          </div>
          {stockItems.map((item, i) => <NewsCard key={`stock-${i}`} item={item} />)}
        </>
      )}

      {/* 거시 환경 뉴스 */}
      {macroItems.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: "#6b7280", margin: "14px 0 8px", fontWeight: 600 }}>
            🌐 거시 환경 뉴스 (국제 정세 · 금리 · 무역)
          </div>
          {macroItems.map((item, i) => <NewsCard key={`macro-${i}`} item={item} />)}
        </>
      )}

      {data?.as_of && (
        <div style={{ fontSize: 11, color: "#4b5563", marginTop: 8, textAlign: "right" }}>
          기준: {new Date(data.as_of).toLocaleString("ko-KR")} · 30분 캐시
        </div>
      )}
    </div>
  );
}
