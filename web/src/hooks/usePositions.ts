import { useQuery } from "@tanstack/react-query";
import { Position } from "@/types/monitor";
import { apiGet } from "@/lib/api/client";

export function usePositions() {
  return useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: () => apiGet<Position[]>("/api/positions"),
    staleTime: Infinity,
  });
}
