import { useQuery } from "@tanstack/react-query";
import { StrategyLifecycleEntry } from "@/types/research";
import { apiGet } from "@/lib/api/client";

export function useStrategyLifecycle() {
  return useQuery<StrategyLifecycleEntry[]>({
    queryKey: ["strategy-lifecycle"],
    queryFn: () => apiGet<StrategyLifecycleEntry[]>("/api/strategy-lifecycle"),
    staleTime: Infinity,
  });
}
