import { useQuery } from "@tanstack/react-query";
import { Fill } from "@/types/trade";
import { apiGet } from "@/lib/api/client";

export function useFills() {
  return useQuery<Fill[]>({
    queryKey: ["fills"],
    queryFn: () => apiGet<Fill[]>("/api/fills"),
    staleTime: Infinity,
  });
}
