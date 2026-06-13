import { useQuery } from "@tanstack/react-query";
import { Position } from "@/types/monitor";
import { mockPositions } from "@/lib/mock/positions";

export function usePositions() {
  return useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: () => mockPositions(),
    staleTime: Infinity,
  });
}
