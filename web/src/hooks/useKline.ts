import { useQuery } from "@tanstack/react-query";
import { Bar } from "@/types/domain";
import { mockKline } from "@/lib/mock/kline";

export function useKline(symbol: string) {
  return useQuery<Bar[]>({
    queryKey: ["kline", symbol],
    queryFn: () => mockKline(),
    staleTime: Infinity,
  });
}
