import type { AnalyzeResponse } from "../api/client";

interface Props {
  data: AnalyzeResponse;
}

function fmt(val: number | null | undefined, digits = 1, suffix = ""): string {
  if (val == null) return "—";
  return val.toFixed(digits) + suffix;
}

function fmtLarge(val: number | null | undefined): string {
  if (val == null) return "—";
  if (val >= 1e12) return (val / 1e12).toFixed(2) + "T";
  if (val >= 1e9) return (val / 1e9).toFixed(1) + "B";
  if (val >= 1e6) return (val / 1e6).toFixed(1) + "M";
  return val.toLocaleString();
}

function Metric({
  label, value, hint, color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div style={{
      background: "#1f2937", borderRadius: 8, padding: "12px 14px",
      display: "flex", flexDirection: "column", gap: 4, minWidth: 100,
    }}>
      <div style={{ fontSize: 11, color: "#6b7280" }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 700,
        color: color ?? (value === "—" ? "#4b5563" : "#f9fafb"),
      }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: 11, color: "#9ca3af" }}>{hint}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        fontSize: 12, fontWeight: 600, color: "#6b7280",
        marginBottom: 10, textTransform: "uppercase", letterSpacing: 1,
      }}>
        {title}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {children}
      </div>
    </div>
  );
}

export function MetricsPanel({ data }: Props) {
  const val = data.valuation_detail as Record<string, number | null> | undefined;
  const mom = data.momentum_detail?.components as Record<string, number | null> | undefined;
  const risk = data.risk_detail?.components as Record<string, number | null> | undefined;
  const macro = data.macro_detail?.components as Record<string, number | null> | undefined;

  // 밸류에이션 데이터 있는지 확인
  const hasVal = val && Object.values(val).some((v) => v != null);
  const hasMom = mom && Object.keys(mom).length > 0;
  const hasRisk = risk && Object.keys(risk).length > 0;

  // ROE, ROA는 factor_scores 아닌 별도 상세에 없으면 표시 안 함
  // momentum components 키: rsi, macd_signal, bb_pct, adx, vol_ratio, ret_1m, ret_3m, etc.

  return (
    <div style={{
      background: "#111827", border: "1px solid #374151",
      borderRadius: 12, padding: 24, color: "#f9fafb",
    }}>
      <h3 style={{ margin: "0 0 20px", fontSize: 16, fontWeight: 600 }}>
        📊 수치 분석
      </h3>

      {/* 밸류에이션 */}
      <Section title="밸류에이션">
        <Metric label="PER (현재)" value={fmt(val?.per)} hint="주가수익비율" />
        <Metric label="PER (예상)" value={fmt(val?.forward_pe)} hint="Forward P/E" />
        <Metric label="PBR" value={fmt(val?.pbr)} hint="주가순자산비율" />
        <Metric label="PSR" value={fmt(val?.psr)} hint="주가매출비율" />
        <Metric label="EV/EBITDA" value={fmt(val?.ev_ebitda)} />
        <Metric label="PEG" value={fmt(val?.peg_ratio, 2)} hint="성장대비PER" />
        <Metric
          label="배당수익률"
          value={fmt(val?.dividend_yield, 2, "%")}
          hint="연간 배당 / 주가"
        />
        <Metric label="EPS" value={fmt(val?.eps, 2)} hint="주당순이익" />
        {val?.market_cap != null && (
          <Metric label="시가총액" value={fmtLarge(val.market_cap)} />
        )}
        {val?.roe != null && (
          <Metric label="ROE" value={fmt(val.roe, 1, "%")}
            hint="자기자본이익률"
            color={val.roe > 15 ? "#22c55e" : val.roe < 5 ? "#ef4444" : "#f59e0b"} />
        )}
        {val?.revenue_growth != null && (
          <Metric label="매출성장(YoY)" value={fmt(val.revenue_growth, 1, "%")}
            color={val.revenue_growth > 0 ? "#22c55e" : "#ef4444"} />
        )}
        {val?.fcf != null && (
          <Metric label="잉여현금흐름" value={fmtLarge(val.fcf)} hint="FCF" />
        )}
        {val?.per_5y_pct != null && (
          <Metric
            label="PER 5년 분위"
            value={fmt(val.per_5y_pct, 0, "%ile")}
            hint="낮을수록 저평가"
            color={val.per_5y_pct < 30 ? "#22c55e" : val.per_5y_pct > 70 ? "#ef4444" : "#f59e0b"}
          />
        )}
        {!hasVal && (
          <div style={{ fontSize: 13, color: "#6b7280", alignSelf: "center" }}>
            yfinance에서 데이터를 가져오는 중이거나 일시적으로 불가합니다.
          </div>
        )}
      </Section>

      {/* 모멘텀 수치 */}
      {hasMom && (
        <Section title="모멘텀 지표">
          {mom?.rsi != null && (
            <Metric
              label="RSI (14)"
              value={fmt(mom.rsi, 1)}
              hint={mom.rsi > 70 ? "과매수" : mom.rsi < 30 ? "과매도" : "중립"}
              color={mom.rsi > 70 ? "#ef4444" : mom.rsi < 30 ? "#22c55e" : "#f9fafb"}
            />
          )}
          {mom?.macd_signal != null && (
            <Metric label="MACD 신호" value={fmt(mom.macd_signal, 2)}
              color={mom.macd_signal > 0 ? "#22c55e" : "#ef4444"} />
          )}
          {mom?.bb_pct != null && (
            <Metric label="볼린저 위치" value={fmt(mom.bb_pct, 1, "%")}
              hint="0%=하단, 100%=상단" />
          )}
          {mom?.adx != null && (
            <Metric label="ADX" value={fmt(mom.adx, 1)}
              hint={mom.adx > 25 ? "추세 강함" : "추세 약함"} />
          )}
          {mom?.vol_ratio != null && (
            <Metric label="거래량 비율" value={fmt(mom.vol_ratio, 2, "x")}
              hint="20일 평균 대비"
              color={mom.vol_ratio > 1.5 ? "#22c55e" : "#f9fafb"} />
          )}
          {mom?.ret_1m != null && (
            <Metric label="1개월 수익률" value={fmt(mom.ret_1m, 1, "%")}
              color={mom.ret_1m > 0 ? "#22c55e" : "#ef4444"} />
          )}
          {mom?.ret_3m != null && (
            <Metric label="3개월 수익률" value={fmt(mom.ret_3m, 1, "%")}
              color={mom.ret_3m > 0 ? "#22c55e" : "#ef4444"} />
          )}
          {mom?.ret_6m != null && (
            <Metric label="6개월 수익률" value={fmt(mom.ret_6m, 1, "%")}
              color={mom.ret_6m > 0 ? "#22c55e" : "#ef4444"} />
          )}
        </Section>
      )}

      {/* 리스크 수치 */}
      {hasRisk && (
        <Section title="리스크 지표">
          {risk?.beta != null && (
            <Metric label="베타" value={fmt(risk.beta, 2)}
              hint="시장 대비 변동성"
              color={risk.beta > 1.5 ? "#ef4444" : risk.beta < 0.8 ? "#22c55e" : "#f9fafb"} />
          )}
          {risk?.atr_pct != null && (
            <Metric label="ATR%" value={fmt(risk.atr_pct, 2, "%")}
              hint="평균 일일 변동폭" />
          )}
          {risk?.max_drawdown != null && (
            <Metric label="최대 낙폭" value={fmt(risk.max_drawdown, 1, "%")}
              color="#ef4444" />
          )}
          {risk?.sharpe != null && (
            <Metric label="샤프 비율" value={fmt(risk.sharpe, 2)}
              hint={risk.sharpe > 1 ? "양호" : "낮음"}
              color={risk.sharpe > 1 ? "#22c55e" : "#f59e0b"} />
          )}
        </Section>
      )}

      {/* 거시환경 수치 */}
      {macro && Object.keys(macro).length > 0 && (
        <Section title="거시 지표">
          {macro?.fed_rate != null && (
            <Metric label="기준금리" value={fmt(macro.fed_rate, 2, "%")} />
          )}
          {macro?.unemployment != null && (
            <Metric label="실업률" value={fmt(macro.unemployment, 1, "%")} />
          )}
          {macro?.cpi_yoy != null && (
            <Metric label="소비자물가(YoY)" value={fmt(macro.cpi_yoy, 1, "%")}
              color={macro.cpi_yoy > 4 ? "#ef4444" : macro.cpi_yoy < 2 ? "#22c55e" : "#f59e0b"} />
          )}
          {macro?.yield_10y != null && (
            <Metric label="10년 국채" value={fmt(macro.yield_10y, 2, "%")} />
          )}
          {macro?.vix != null && (
            <Metric label="VIX 공포지수" value={fmt(macro.vix, 1)}
              hint={macro.vix > 30 ? "공포" : macro.vix < 15 ? "안정" : "보통"}
              color={macro.vix > 30 ? "#ef4444" : macro.vix < 15 ? "#22c55e" : "#f59e0b"} />
          )}
          {macro?.dxy != null && (
            <Metric label="달러인덱스 DXY" value={fmt(macro.dxy, 1)} />
          )}
        </Section>
      )}
    </div>
  );
}
