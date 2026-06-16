import { useQuery } from "@tanstack/react-query";
import { MarketRow } from "@/types/domain";
import { apiGet } from "@/lib/api/client";

export function useMarkets() {
  return useQuery<MarketRow[]>({
    queryKey: ["markets"],
    queryFn: () => apiGet<MarketRow[]>("/api/markets"),
    staleTime: Infinity,
  });
}
