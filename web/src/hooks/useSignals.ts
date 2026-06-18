import { useQuery } from "@tanstack/react-query";
import type { ReplaySignal } from "@/types/domain";
import { apiGet } from "@/lib/api/client";

export function useSignals(symbol: string) {
  return useQuery<ReplaySignal[]>({
    queryKey: ["signals", symbol],
    queryFn: () => apiGet<ReplaySignal[]>(`/api/signals/${symbol}`),
    staleTime: Infinity,
  });
}
