import { useQuery } from "@tanstack/react-query";
import { Fill } from "@/types/trade";
import { mockFills } from "@/lib/mock/fills";

export function useFills() {
  return useQuery<Fill[]>({
    queryKey: ["fills"],
    queryFn: () => mockFills(),
    staleTime: Infinity,
  });
}
