import { useQuery } from "@tanstack/react-query";
import { SentimentPoint } from "@/types/domain";
import { apiGet } from "@/lib/api/client";

export function useSentiment(symbol: string) {
  return useQuery<SentimentPoint[]>({
    queryKey: ["sentiment", symbol],
    queryFn: () => apiGet<SentimentPoint[]>(`/api/sentiment/${symbol}`),
    staleTime: Infinity,
  });
}
