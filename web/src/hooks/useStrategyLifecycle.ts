import { useQuery } from "@tanstack/react-query";
import { StrategyLifecycleEntry } from "@/types/research";
import { mockStrategyLifecycle } from "@/lib/mock/strategy_lifecycle";

export function useStrategyLifecycle() {
  return useQuery<StrategyLifecycleEntry[]>({
    queryKey: ["strategy-lifecycle"],
    queryFn: () => mockStrategyLifecycle(),
    staleTime: Infinity,
  });
}
