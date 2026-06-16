import { useQuery } from "@tanstack/react-query";
import { Order } from "@/types/trade";
import { apiGet } from "@/lib/api/client";

export function useOrders() {
  return useQuery<Order[]>({
    queryKey: ["orders"],
    queryFn: () => apiGet<Order[]>("/api/orders"),
    staleTime: Infinity,
  });
}
