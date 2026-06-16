import { useQuery } from "@tanstack/react-query";
import { AccountSnapshot } from "@/types/trade";
import { apiGet } from "@/lib/api/client";

export function useAccount() {
  return useQuery<AccountSnapshot[]>({
    queryKey: ["account"],
    queryFn: () => apiGet<AccountSnapshot[]>("/api/account"),
    staleTime: Infinity,
  });
}
