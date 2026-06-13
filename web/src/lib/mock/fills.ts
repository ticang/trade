import { Fill } from "@/types/trade";

// Deterministic recent fills linked to submitted/partial/filled orders.
export function mockFills(): Fill[] {
  return [
    {
      fill_id: "fill-2001",
      order_id: "ord-1001",
      symbol: "600519",
      side: "buy",
      price: 1679.5,
      qty: 100,
      ts: 1718300100000,
    },
    {
      fill_id: "fill-2002",
      order_id: "ord-1002",
      symbol: "300750",
      side: "sell",
      price: 184.8,
      qty: 80,
      ts: 1718303700000,
    },
    {
      fill_id: "fill-2003",
      order_id: "ord-1001",
      symbol: "600519",
      side: "buy",
      price: 1680.2,
      qty: 50,
      ts: 1718296400000,
    },
    {
      fill_id: "fill-2004",
      order_id: "ord-1002",
      symbol: "300750",
      side: "sell",
      price: 185.1,
      qty: 120,
      ts: 1718292800000,
    },
  ];
}
