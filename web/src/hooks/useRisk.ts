import { useQuery } from "@tanstack/react-query";
import { RiskState } from "@/types/monitor";
import { mockRisk } from "@/lib/mock/risk";

export function useRisk() {
  return useQuery<RiskState>({
    queryKey: ["risk"],
    queryFn: () => mockRisk(),
    staleTime: Infinity,
  });
}
