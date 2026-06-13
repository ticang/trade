import { useQuery } from "@tanstack/react-query";
import { AccountSnapshot } from "@/types/trade";
import { mockAccount } from "@/lib/mock/account";

export function useAccount() {
  return useQuery<AccountSnapshot[]>({
    queryKey: ["account"],
    queryFn: () => mockAccount(),
    staleTime: Infinity,
  });
}
