import { useState, useEffect } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";
import { warmUpBackend } from "../api/client";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

export function LoginPage() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [originBlocked, setOriginBlocked] = useState<string | null>(null);

  // 로그인 화면이 뜨는 순간 백엔드를 미리 깨운다. 사용자가 Google 창을
  // 거치는 동안 cold start가 끝나므로 첫 로그인이 타임아웃으로 죽지 않는다.
  useEffect(() => {
    warmUpBackend();
  }, []);

  // Google이 이 출처(origin)를 허용하는지 미리 확인한다. 허용돼 있지 않으면
  // 버튼은 멀쩡히 그려지지만 눌러도 아무 일도 일어나지 않아서 원인을 알 수
  // 없다 — 그래서 누르기 전에 미리 알려준다.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const origin = window.location.origin;
    fetch(
      `https://accounts.google.com/gsi/status?client_id=${encodeURIComponent(
        GOOGLE_CLIENT_ID,
      )}&as=preflight`,
      { mode: "cors" },
    )
      .then((r) => {
        if (r.status === 403) setOriginBlocked(origin);
      })
      // 네트워크 차단·확장프로그램 등으로 확인 자체가 실패하면 조용히 넘어간다.
      .catch(() => {});
  }, []);

  async function handleSuccess(credentialResponse: { credential?: string }) {
    if (!credentialResponse.credential) return;
    setLoading(true);
    setError(null);
    try {
      await login(credentialResponse.credential);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail) {
        setError(detail);
      } else if (e?.code === "ECONNABORTED" || !e?.response) {
        setError(
          "서버에 연결하지 못했습니다. 무료 서버가 절전에서 깨어나는 중일 수 있습니다 — " +
            "30초쯤 후 다시 시도해 주세요.",
        );
      } else {
        setError("로그인에 실패했습니다. 다시 시도해 주세요.");
      }
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
          {!GOOGLE_CLIENT_ID ? (
            <div
              style={{
                padding: "12px 14px",
                background: "#2d0c0c",
                border: "1px solid #7f1d1d",
                borderRadius: 8,
                color: "#fca5a5",
                fontSize: 12,
                lineHeight: 1.6,
                textAlign: "left",
              }}
            >
              <strong>설정 오류:</strong> 빌드에 <code>VITE_GOOGLE_CLIENT_ID</code>가
              없어 Google 로그인을 초기화할 수 없습니다.
              <br />
              Vercel → Settings → Environment Variables 에 값을 추가한 뒤 재배포하세요.
            </div>
          ) : originBlocked ? (
            <div
              style={{
                padding: "12px 14px",
                background: "#2d0c0c",
                border: "1px solid #7f1d1d",
                borderRadius: 8,
                color: "#fca5a5",
                fontSize: 12,
                lineHeight: 1.7,
                textAlign: "left",
              }}
            >
              <strong>이 주소는 Google에 등록되어 있지 않습니다.</strong>
              <br />
              Google Cloud Console → 사용자 인증 정보 → 해당 OAuth 클라이언트 →
              <b> 승인된 JavaScript 원본</b>에 아래 주소를 추가한 뒤 몇 분 기다렸다
              새로고침하세요.
              <div
                style={{
                  marginTop: 8,
                  padding: "6px 8px",
                  background: "#111827",
                  borderRadius: 6,
                  color: "#e5e7eb",
                  fontFamily: "monospace",
                  fontSize: 12,
                  wordBreak: "break-all",
                }}
              >
                {originBlocked}
              </div>
            </div>
          ) : loading ? (
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
