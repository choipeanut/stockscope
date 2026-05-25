import { useEffect, useState } from "react";

interface Props {
  asOf: string;           // ISO string
  staleAfterMinutes?: number; // default 60
}

function elapsed(asOf: string): number {
  return Math.floor((Date.now() - new Date(asOf).getTime()) / 1000);
}

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}초 전`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  return `${Math.floor(seconds / 86400)}일 전`;
}

export function FreshnessBadge({ asOf, staleAfterMinutes = 60 }: Props) {
  const [age, setAge] = useState(() => elapsed(asOf));

  useEffect(() => {
    const id = setInterval(() => setAge(elapsed(asOf)), 30_000);
    return () => clearInterval(id);
  }, [asOf]);

  const staleThreshold = staleAfterMinutes * 60;
  const isStale = age > staleThreshold;
  const isFresh = age < 300; // under 5 min

  const bg = isStale ? "#1c1917" : isFresh ? "#052e16" : "#1f2937";
  const color = isStale ? "#d97706" : isFresh ? "#4ade80" : "#9ca3af";
  const border = isStale ? "#92400e" : isFresh ? "#166534" : "#374151";
  const dot = isStale ? "🟡" : isFresh ? "🟢" : "⚪";

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 4,
        background: bg,
        color,
        border: `1px solid ${border}`,
      }}
    >
      {dot} {fmtAge(age)}
    </span>
  );
}
