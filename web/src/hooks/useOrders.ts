import { useQuery } from "@tanstack/react-query";
import { Order } from "@/types/trade";
import { mockOrders } from "@/lib/mock/orders";

export function useOrders() {
  return useQuery<Order[]>({
    queryKey: ["orders"],
    queryFn: () => mockOrders(),
    staleTime: Infinity,
  });
}
