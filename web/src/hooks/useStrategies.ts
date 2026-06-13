import { useQuery } from "@tanstack/react-query";
import { Strategy } from "@/types/monitor";
import { mockStrategies } from "@/lib/mock/strategies";

export function useStrategies() {
  return useQuery<Strategy[]>({
    queryKey: ["strategies"],
    queryFn: () => mockStrategies(),
    staleTime: Infinity,
  });
}
