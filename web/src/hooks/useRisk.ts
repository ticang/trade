import { useQuery } from "@tanstack/react-query";
import { RiskState } from "@/types/monitor";
import { apiGet } from "@/lib/api/client";

export function useRisk() {
  return useQuery<RiskState>({
    queryKey: ["risk"],
    queryFn: () => apiGet<RiskState>("/api/risk"),
    staleTime: Infinity,
  });
}
