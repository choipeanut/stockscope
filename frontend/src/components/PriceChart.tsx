import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OhlcvRow } from "../api/client";

interface Props {
  ohlcv: OhlcvRow[];
  ticker: string;
  buyPrice?: number;   // 매수 평균가 (native 통화) — 수평 기준선
  buyDate?: string;    // 매수 시점 ISO — 이 날짜 이후만 표시
  title?: string;
  maxPoints?: number;
}

function formatDate(dateStr: string): string {
  return dateStr.slice(0, 10);
}

export function PriceChart({ ohlcv, ticker, buyPrice, buyDate, title, maxPoints = 180 }: Props) {
  if (!ohlcv || ohlcv.length === 0) return null;

  // 매수 시점 이후만 필터 (있으면)
  let rows = ohlcv;
  if (buyDate) {
    const buyDay = buyDate.slice(0, 10);
    const filtered = ohlcv.filter((r) => formatDate(r.date) >= buyDay);
    if (filtered.length >= 2) rows = filtered;
  }

  const data = rows.slice(-maxPoints).map((row) => ({
    date: formatDate(row.date),
    close: Number(row.close.toFixed(2)),
    volume: row.volume,
  }));

  const prices = data.map((d) => d.close);
  const minP = Math.min(...prices, buyPrice ?? Infinity);
  const maxP = Math.max(...prices, buyPrice ?? -Infinity);
  const padding = (maxP - minP) * 0.05 || 1;

  // 매수가 대비 현재 등락에 따라 선 색상
  const lastClose = prices[prices.length - 1];
  const up = buyPrice != null ? lastClose >= buyPrice : true;
  const lineColor = buyPrice != null ? (up ? "#22c55e" : "#ef4444") : "#3b82f6";

  const heading = title ?? `${ticker} 가격 차트${buyDate ? " (매수 후)" : " (최근 180일)"}`;

  return (
    <div
      style={{
        background: "#111827",
        border: "1px solid #374151",
        borderRadius: 12,
        padding: 20,
        color: "#f9fafb",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{heading}</h3>
        {buyPrice != null && (
          <span style={{ fontSize: 12, color: "#9ca3af" }}>
            매수가 <span style={{ color: "#f59e0b", fontWeight: 600 }}>{buyPrice.toLocaleString()}</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id={`grad-${ticker}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={lineColor} stopOpacity={0.3} />
              <stop offset="95%" stopColor={lineColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            tickLine={false}
            interval={Math.max(0, Math.floor(data.length / 6))}
          />
          <YAxis
            domain={[minP - padding, maxP + padding]}
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => v.toLocaleString()}
            width={70}
          />
          <Tooltip
            contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 6 }}
            labelStyle={{ color: "#9ca3af", fontSize: 12 }}
            itemStyle={{ color: lineColor }}
            formatter={(v) => [(v as number).toLocaleString(), "종가"]}
          />
          {buyPrice != null && (
            <ReferenceLine
              y={buyPrice}
              stroke="#f59e0b"
              strokeDasharray="5 4"
              strokeWidth={1.5}
              label={{ value: "매수가", position: "insideTopLeft", fill: "#f59e0b", fontSize: 11 }}
            />
          )}
          <Area
            type="monotone"
            dataKey="close"
            stroke={lineColor}
            strokeWidth={2}
            fill={`url(#grad-${ticker})`}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
