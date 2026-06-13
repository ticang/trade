import { useQuery } from "@tanstack/react-query";
import { MarketRow } from "@/types/domain";
import { mockMarkets } from "@/lib/mock/markets";

export function useMarkets() {
  return useQuery<MarketRow[]>({
    queryKey: ["markets"],
    queryFn: () => mockMarkets(),
    staleTime: Infinity,
  });
}
