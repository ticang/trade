import { useQuery } from "@tanstack/react-query";
import { FactorEval } from "@/types/research";
import { mockFactorEval } from "@/lib/mock/factor_eval";

export function useFactorEval() {
  return useQuery<FactorEval[]>({
    queryKey: ["factor-eval"],
    queryFn: () => mockFactorEval(),
    staleTime: Infinity,
  });
}
