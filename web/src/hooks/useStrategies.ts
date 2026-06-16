import { useQuery } from "@tanstack/react-query";
import { Strategy } from "@/types/monitor";
import { apiGet } from "@/lib/api/client";

export function useStrategies() {
  return useQuery<Strategy[]>({
    queryKey: ["strategies"],
    queryFn: () => apiGet<Strategy[]>("/api/strategies"),
    staleTime: Infinity,
  });
}
