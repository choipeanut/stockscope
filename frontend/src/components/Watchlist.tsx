import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface WatchlistItem {
  id: number;
  ticker: string;
  market: string;
  added_ts: string;
}

interface Props {
  onDrillDown?: (ticker: string, market: string) => void;
}

export function Watchlist({ onDrillDown }: Props) {
  const qc = useQueryClient();

  const { data, isFetching } = useQuery<{ watchlist: WatchlistItem[] }>({
    queryKey: ["watchlist"],
    queryFn: async () => (await api.get("/watchlist")).data,
    refetchOnWindowFocus: false,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/watchlist/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const items = data?.watchlist ?? [];

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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>⭐ 관심 종목</h4>
        {isFetching && <span style={{ fontSize: 12, color: "#6b7280" }}>갱신 중...</span>}
      </div>

      {items.length === 0 ? (
        <div style={{ fontSize: 13, color: "#6b7280", textAlign: "center", padding: "12px 0" }}>
          관심 종목 없음
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {items.map((item) => (
            <div
              key={item.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "#1f2937",
                borderRadius: 6,
                padding: "7px 10px",
              }}
            >
              <div>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{item.ticker}</span>
                <span style={{ fontSize: 11, color: "#6b7280", marginLeft: 6 }}>{item.market}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {onDrillDown && (
                  <button
                    onClick={() => onDrillDown(item.ticker, item.market)}
                    style={{
                      background: "transparent", border: "1px solid #374151",
                      borderRadius: 4, color: "#93c5fd", padding: "2px 8px",
                      fontSize: 11, cursor: "pointer",
                    }}
                  >
                    분석
                  </button>
                )}
                <button
                  onClick={() => deleteMutation.mutate(item.id)}
                  disabled={deleteMutation.isPending}
                  style={{
                    background: "transparent", border: "1px solid #374151",
                    borderRadius: 4, color: "#9ca3af", padding: "2px 8px",
                    fontSize: 11, cursor: "pointer",
                  }}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* Standalone add-to-watchlist button to embed in analysis view */
interface AddButtonProps {
  ticker: string;
  market: string;
}

export function WatchlistAddButton({ ticker, market }: AddButtonProps) {
  const qc = useQueryClient();

  const { data } = useQuery<{ watchlist: WatchlistItem[] }>({
    queryKey: ["watchlist"],
    queryFn: async () => (await api.get("/watchlist")).data,
    refetchOnWindowFocus: false,
  });

  const isWatched = data?.watchlist.some(
    (w) => w.ticker === ticker && w.market === market,
  ) ?? false;

  const addMutation = useMutation({
    mutationFn: async () =>
      api.post("/watchlist", null, { params: { ticker, market } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  if (isWatched) {
    return (
      <span style={{ fontSize: 13, color: "#f59e0b" }}>⭐ 관심종목 등록됨</span>
    );
  }

  return (
    <button
      onClick={() => addMutation.mutate()}
      disabled={addMutation.isPending}
      style={{
        background: "transparent",
        border: "1px solid #374151",
        borderRadius: 6,
        color: "#9ca3af",
        padding: "5px 12px",
        fontSize: 13,
        cursor: "pointer",
      }}
    >
      {addMutation.isPending ? "추가 중..." : "⭐ 관심종목 추가"}
    </button>
  );
}
