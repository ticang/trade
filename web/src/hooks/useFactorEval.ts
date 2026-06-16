import { useQuery } from "@tanstack/react-query";
import { FactorEval } from "@/types/research";
import { apiGet } from "@/lib/api/client";

export function useFactorEval() {
  return useQuery<FactorEval[]>({
    queryKey: ["factor-eval"],
    queryFn: () => apiGet<FactorEval[]>("/api/factor-eval"),
    staleTime: Infinity,
  });
}
