import { AccountSnapshot } from "@/types/trade";

// Deterministic account snapshots for the two mock accounts.
export function mockAccount(): AccountSnapshot[] {
  return [
    {
      account_id: "acct1",
      cash: 120000,
      market_value: 280060,
      total: 400060,
      available: 118500,
    },
    {
      account_id: "acct2",
      cash: 85000,
      market_value: 49120,
      total: 134120,
      available: 82000,
    },
  ];
}
