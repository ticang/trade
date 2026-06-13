import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/types/monitor";
import { mockAlerts } from "@/lib/mock/alerts";

export function useAlerts() {
  return useQuery<Alert[]>({
    queryKey: ["alerts"],
    queryFn: () => mockAlerts(),
    staleTime: Infinity,
  });
}
