import { useQuery } from "@tanstack/react-query";
import { SentimentPoint } from "@/types/domain";
import { mockSentiment } from "@/lib/mock/sentiment";

export function useSentiment(symbol: string) {
  return useQuery<SentimentPoint[]>({
    queryKey: ["sentiment", symbol],
    queryFn: () => mockSentiment(),
    staleTime: Infinity,
  });
}
