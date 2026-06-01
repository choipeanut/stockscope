import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { fetchAnalysis } from "./api/client";
import { ScoreCard } from "./components/ScoreCard";
import { PriceChart } from "./components/PriceChart";
import { FactorBreakdown } from "./components/FactorBreakdown";
import { ScenarioPanel } from "./components/ScenarioPanel";
import { TradeForm } from "./components/TradeForm";
import { Portfolio } from "./components/Portfolio";
import { ScreenTable } from "./components/ScreenTable";
import { MacroDashboard } from "./components/MacroDashboard";
import { Watchlist, WatchlistAddButton } from "./components/Watchlist";
import { NewsPanel } from "./components/NewsPanel";
import { MetricsPanel } from "./components/MetricsPanel";
import { LoginPage } from "./components/LoginPage";
import { PredictPanel } from "./components/PredictPanel";
import { AuthProvider, useAuth } from "./contexts/AuthContext";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 5 * 60 * 1000 } },
});

const EXAMPLES = [
  { ticker: "AAPL", market: "NASDAQ" as const, label: "AAPL · Apple" },
  { ticker: "MSFT", market: "NASDAQ" as const, label: "MSFT · Microsoft" },
  { ticker: "005930", market: "KOSDAQ" as const, label: "005930 · 삼성전자" },
  { ticker: "247540", market: "KOSDAQ" as const, label: "247540 · 에코프로비엠" },
];

function AnalysisView({ initialTicker = "", initialMarket = "NASDAQ" as "KOSDAQ" | "NASDAQ" }) {
  const [ticker, setTicker] = useState(initialTicker);
  const [market, setMarket] = useState<"KOSDAQ" | "NASDAQ">(initialMarket);
  const [submitted, setSubmitted] = useState<{ ticker: string; market: string } | null>(
    initialTicker ? { ticker: initialTicker, market: initialMarket } : null
  );

  const { data, isFetching, error } = useQuery({
    queryKey: ["analyze", submitted?.ticker, submitted?.market],
    queryFn: () => fetchAnalysis(submitted!.ticker, submitted!.market),
    enabled: !!submitted,
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setSubmitted({ ticker: t, market });
  }

  function runExample(ex: (typeof EXAMPLES)[number]) {
    setTicker(ex.ticker);
    setMarket(ex.market);
    setSubmitted(ex);
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#f9fafb", padding: "32px 16px" }}>
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800, margin: 0 }}>📈 StockScope</h1>
          <p style={{ color: "#9ca3af", marginTop: 8 }}>
            KOSDAQ &amp; NASDAQ 주식 분석 · 모의투자 · 종목 발굴
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap", marginBottom: 24 }}
        >
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="티커 입력 (예: AAPL, 005930)"
            style={{
              background: "#1f2937", border: "1px solid #374151", borderRadius: 8,
              color: "#f9fafb", padding: "10px 16px", fontSize: 15, width: 260, outline: "none",
            }}
          />
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value as "KOSDAQ" | "NASDAQ")}
            style={{
              background: "#1f2937", border: "1px solid #374151", borderRadius: 8,
              color: "#f9fafb", padding: "10px 12px", fontSize: 15, outline: "none",
            }}
          >
            <option value="NASDAQ">NASDAQ</option>
            <option value="KOSDAQ">KOSDAQ</option>
          </select>
          <button
            type="submit"
            disabled={isFetching}
            style={{
              background: "#3b82f6", border: "none", borderRadius: 8, color: "#fff",
              padding: "10px 24px", fontSize: 15, fontWeight: 600,
              cursor: isFetching ? "not-allowed" : "pointer", opacity: isFetching ? 0.7 : 1,
            }}
          >
            {isFetching ? "분석 중..." : "분석"}
          </button>
        </form>

        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <span style={{ color: "#6b7280", fontSize: 13, marginRight: 8 }}>예시:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={`${ex.ticker}-${ex.market}`}
              onClick={() => runExample(ex)}
              style={{
                background: "transparent", border: "1px solid #374151", borderRadius: 6,
                color: "#9ca3af", padding: "4px 10px", margin: "0 4px", cursor: "pointer", fontSize: 13,
              }}
            >
              {ex.label}
            </button>
          ))}
        </div>

        {error && (
          <div style={{
            background: "#1f2937", border: "1px solid #ef4444", borderRadius: 8,
            padding: "12px 16px", color: "#ef4444", textAlign: "center", marginBottom: 24,
          }}>
            {(error as Error).message}
          </div>
        )}

        {data && (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
              <ScoreCard data={data} />
              <div style={{ flex: 1, minWidth: 320 }}>
                <PriceChart ohlcv={data.ohlcv} ticker={data.ticker} />
              </div>
            </div>

            <div style={{ background: "#111827", border: "1px solid #374151", borderRadius: 12, padding: 24 }}>
              <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>
                팩터 상세 ({data.unavailable.length > 0
                  ? `${6 - data.unavailable.length}/6 팩터 사용 가능`
                  : "6/6 팩터 사용 가능"})
              </h3>
              <FactorBreakdown data={data} />
            </div>

            {data.key_required && data.key_required.length > 0 && (
              <div style={{
                background: "#1c1917", border: "1px solid #92400e",
                borderRadius: 8, padding: "10px 16px", fontSize: 13, color: "#d97706",
              }}>
                다음 API 키가 설정되면 추가 팩터를 계산할 수 있습니다:{" "}
                {data.key_required.join(", ")}
              </div>
            )}

            {data.macro_detail?.regime && (
              <div style={{ background: "#111827", border: "1px solid #374151", borderRadius: 12, padding: "16px 24px" }}>
                <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>거시 국면</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{data.macro_detail.regime}</div>
                  </div>
                  {data.macro_detail.sector_hints?.length > 0 && (
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>섹터 힌트</div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {data.macro_detail.sector_hints.map((h, i) => (
                          <span key={i} style={{ background: "#1f2937", borderRadius: 6, padding: "4px 10px", fontSize: 12, color: "#d1d5db" }}>
                            {h}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {data.scenarios && data.scenarios.length > 0 && (
              <div style={{ background: "#111827", border: "1px solid #374151", borderRadius: 12, padding: 24 }}>
                <ScenarioPanel scenarios={data.scenarios} />
              </div>
            )}

            <MetricsPanel data={data} />
            <NewsPanel ticker={data.ticker} market={data.market} />

            <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 280 }}>
                <TradeForm
                  ticker={data.ticker}
                  market={data.market}
                  name={data.name}
                  currentPrice={data.ohlcv.length > 0 ? data.ohlcv[data.ohlcv.length - 1].close : undefined}
                />
              </div>
              <div style={{ paddingTop: 20 }}>
                <WatchlistAddButton ticker={data.ticker} market={data.market} />
              </div>
            </div>

            <div style={{
              padding: "10px 16px", background: "#111827",
              border: "1px solid #1f2937", borderRadius: 8,
              fontSize: 11, color: "#6b7280", textAlign: "center",
            }}>
              ⚠️ {data.notice}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const TAB_STYLE = (active: boolean) => ({
  padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
  fontWeight: active ? 700 : 500, fontSize: 14,
  background: active ? "#3b82f6" : "transparent",
  color: active ? "#fff" : "#9ca3af",
});

function AppShell() {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState<"analyze" | "screen" | "predict" | "macro" | "portfolio">("analyze");
  const [drillTicker, setDrillTicker] = useState("");
  const [drillMarket, setDrillMarket] = useState<"KOSDAQ" | "NASDAQ">("NASDAQ");

  function handleDrillDown(ticker: string, market: string) {
    setDrillTicker(ticker);
    setDrillMarket(market as "KOSDAQ" | "NASDAQ");
    setTab("analyze");
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#f9fafb" }}>
      {/* Nav */}
      <div style={{
        borderBottom: "1px solid #1f2937", padding: "12px 24px",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span style={{ fontWeight: 800, fontSize: 18, marginRight: 16 }}>📈 StockScope</span>
        <button style={TAB_STYLE(tab === "analyze")} onClick={() => setTab("analyze")}>분석</button>
        <button style={TAB_STYLE(tab === "screen")} onClick={() => setTab("screen")}>스크리너</button>
        <button style={TAB_STYLE(tab === "predict")} onClick={() => setTab("predict")}>AI예측</button>
        <button style={TAB_STYLE(tab === "macro")} onClick={() => setTab("macro")}>매크로</button>
        <button style={TAB_STYLE(tab === "portfolio")} onClick={() => setTab("portfolio")}>포트폴리오</button>

        {/* 유저 정보 + 로그아웃 */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {user?.picture && (
            <img
              src={user.picture}
              alt={user.name}
              style={{ width: 28, height: 28, borderRadius: "50%", objectFit: "cover" }}
            />
          )}
          <span style={{ fontSize: 13, color: "#9ca3af" }}>{user?.name}</span>
          <button
            onClick={logout}
            style={{
              background: "transparent", border: "1px solid #374151",
              borderRadius: 6, color: "#6b7280", padding: "4px 10px",
              fontSize: 12, cursor: "pointer",
            }}
          >
            로그아웃
          </button>
        </div>
      </div>

      <div style={{ padding: "24px 16px" }}>
        {tab === "analyze" && (
          <AnalysisView initialTicker={drillTicker} initialMarket={drillMarket} />
        )}
        {tab === "screen" && (
          <div style={{ maxWidth: 1200, margin: "0 auto" }}>
            <ScreenTable onDrillDown={handleDrillDown} />
          </div>
        )}
        {tab === "predict" && (
          <div style={{ maxWidth: 1200, margin: "0 auto" }}>
            <PredictPanel onDrillDown={handleDrillDown} />
          </div>
        )}
        {tab === "macro" && (
          <div style={{ maxWidth: 960, margin: "0 auto" }}>
            <MacroDashboard />
          </div>
        )}
        {tab === "portfolio" && (
          <div style={{ maxWidth: 960, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
            <Portfolio />
            <Watchlist onDrillDown={handleDrillDown} />
          </div>
        )}
      </div>
    </div>
  );
}

function AppRouter() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    // 세션 복원 중 — 빈 화면 (깜빡임 방지)
    return <div style={{ minHeight: "100vh", background: "#0f172a" }} />;
  }

  if (!user) {
    return <LoginPage />;
  }

  return <AppShell />;
}

export default function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </QueryClientProvider>
    </GoogleOAuthProvider>
  );
}
