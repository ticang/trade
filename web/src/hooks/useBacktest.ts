import { useQuery } from "@tanstack/react-query";
import { BacktestResult } from "@/types/research";
import { apiGet } from "@/lib/api/client";

export function useBacktest() {
  return useQuery<BacktestResult>({
    queryKey: ["backtest"],
    queryFn: () => apiGet<BacktestResult>("/api/backtest"),
    staleTime: Infinity,
  });
}
