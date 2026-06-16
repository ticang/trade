import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/types/monitor";
import { apiGet } from "@/lib/api/client";

export function useAlerts() {
  return useQuery<Alert[]>({
    queryKey: ["alerts"],
    queryFn: () => apiGet<Alert[]>("/api/alerts"),
    staleTime: Infinity,
  });
}
