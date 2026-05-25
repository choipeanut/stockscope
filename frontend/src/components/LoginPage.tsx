import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSuccess(credentialResponse: { credential?: string }) {
    if (!credentialResponse.credential) return;
    setLoading(true);
    setError(null);
    try {
      await login(credentialResponse.credential);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "로그인에 실패했습니다. 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0f172a",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        color: "#f9fafb",
        padding: 24,
      }}
    >
      {/* Logo */}
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <div style={{ fontSize: 56, marginBottom: 8 }}>📈</div>
        <h1 style={{ fontSize: 36, fontWeight: 800, margin: 0, letterSpacing: -1 }}>
          StockScope
        </h1>
        <p style={{ color: "#9ca3af", marginTop: 10, fontSize: 15 }}>
          KOSDAQ &amp; NASDAQ 주식 분석 · 모의투자 · 종목 발굴
        </p>
      </div>

      {/* Login card */}
      <div
        style={{
          background: "#111827",
          border: "1px solid #374151",
          borderRadius: 20,
          padding: "40px 48px",
          textAlign: "center",
          maxWidth: 380,
          width: "100%",
        }}
      >
        <h2 style={{ margin: "0 0 6px", fontSize: 20, fontWeight: 700 }}>
          로그인
        </h2>
        <p style={{ color: "#6b7280", margin: "0 0 28px", fontSize: 13 }}>
          나만의 포트폴리오를 관리하세요
        </p>

        {/* Feature bullets */}
        <div style={{ marginBottom: 28, textAlign: "left" }}>
          {[
            "📊 종목 분석 & AI 시나리오",
            "💼 유저별 개인 포트폴리오",
            "🔍 퀀트 스크리너",
            "📰 실시간 뉴스 & 공시",
          ].map((f) => (
            <div
              key={f}
              style={{ fontSize: 13, color: "#9ca3af", padding: "4px 0" }}
            >
              {f}
            </div>
          ))}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "center",
            marginBottom: 16,
          }}
        >
          {loading ? (
            <div
              style={{
                padding: "10px 24px",
                background: "#1f2937",
                borderRadius: 8,
                color: "#9ca3af",
                fontSize: 14,
              }}
            >
              처리 중...
            </div>
          ) : (
            <GoogleLogin
              onSuccess={handleSuccess}
              onError={() => setError("Google 로그인에 실패했습니다.")}
              size="large"
              shape="pill"
              theme="filled_black"
              text="signin_with"
            />
          )}
        </div>

        {error && (
          <div
            style={{
              padding: "8px 12px",
              background: "#2d0c0c",
              border: "1px solid #7f1d1d",
              borderRadius: 8,
              color: "#fca5a5",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {error}
          </div>
        )}

        <p style={{ marginTop: 24, fontSize: 11, color: "#4b5563", lineHeight: 1.6 }}>
          로그인하면 개인 포트폴리오가 자동 생성됩니다.
          <br />
          분석·스크리너 기능은 로그인 없이도 이용할 수 있습니다.
        </p>
      </div>
    </div>
  );
}
