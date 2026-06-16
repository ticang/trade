import { useQuery } from "@tanstack/react-query";
import { Bar } from "@/types/domain";
import { apiGet } from "@/lib/api/client";

export function useKline(symbol: string) {
  return useQuery<Bar[]>({
    queryKey: ["kline", symbol],
    queryFn: () => apiGet<Bar[]>(`/api/kline/${symbol}`),
    staleTime: Infinity,
  });
}
