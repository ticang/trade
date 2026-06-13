import { Position } from "@/types/monitor";

// Deterministic snapshot of holdings across accounts.
export function mockPositions(): Position[] {
  return [
    {
      account_id: "acct1",
      symbol: "600519",
      name: "贵州茅台",
      qty: 100,
      avg_cost: 1650,
      last: 1685.5,
      market_value: 168550,
      pnl: 3550,
      pnl_pct: 2.15,
      weight: 0.32,
    },
    {
      account_id: "acct1",
      symbol: "300750",
      name: "宁德时代",
      qty: 300,
      avg_cost: 178,
      last: 182.7,
      market_value: 54810,
      pnl: 1410,
      pnl_pct: 2.64,
      weight: 0.1,
    },
    {
      account_id: "acct1",
      symbol: "000001",
      name: "平安银行",
      qty: 5000,
      avg_cost: 11.5,
      last: 11.34,
      market_value: 56700,
      pnl: -800,
      pnl_pct: -1.39,
      weight: 0.11,
    },
    {
      account_id: "acct2",
      symbol: "002594",
      name: "比亚迪",
      qty: 200,
      avg_cost: 250,
      last: 245.6,
      market_value: 49120,
      pnl: -880,
      pnl_pct: -1.76,
      weight: 0.09,
    },
  ];
}
