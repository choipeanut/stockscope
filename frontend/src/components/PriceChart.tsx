import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OhlcvRow } from "../api/client";

interface Props {
  ohlcv: OhlcvRow[];
  ticker: string;
}

function formatDate(dateStr: string): string {
  return dateStr.slice(0, 10);
}

export function PriceChart({ ohlcv, ticker }: Props) {
  if (!ohlcv || ohlcv.length === 0) return null;

  // Show last 180 rows for readability
  const data = ohlcv.slice(-180).map((row) => ({
    date: formatDate(row.date),
    close: Number(row.close.toFixed(2)),
    volume: row.volume,
  }));

  const prices = data.map((d) => d.close);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const padding = (maxP - minP) * 0.05;

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
      <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>
        {ticker} 가격 차트 (최근 180일)
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            tickLine={false}
            interval={Math.floor(data.length / 6)}
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
            itemStyle={{ color: "#3b82f6" }}
            formatter={(v) => [(v as number).toLocaleString(), "종가"]}
          />
          <Area
            type="monotone"
            dataKey="close"
            stroke="#3b82f6"
            strokeWidth={2}
            fill="url(#priceGrad)"
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
