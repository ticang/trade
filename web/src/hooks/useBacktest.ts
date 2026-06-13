import { useQuery } from "@tanstack/react-query";
import { BacktestResult } from "@/types/research";
import { mockBacktest } from "@/lib/mock/backtest";

export function useBacktest() {
  return useQuery<BacktestResult>({
    queryKey: ["backtest"],
    queryFn: () => mockBacktest(),
    staleTime: Infinity,
  });
}
