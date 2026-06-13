import { Strategy } from "@/types/monitor";

// Deterministic strategy roster across varied lifecycle states.
export function mockStrategies(): Strategy[] {
  return [
    {
      name: "动量轮动",
      status: "live",
      account_id: "acct1",
      ic: 0.062,
      turnover: 0.45,
      drawdown: -0.08,
      allocation: 0.5,
    },
    {
      name: "情绪反向",
      status: "paper",
      account_id: "acct1",
      ic: 0.038,
      turnover: 0.62,
      drawdown: -0.12,
      allocation: 0.3,
    },
    {
      name: "事件驱动",
      status: "degraded",
      account_id: "acct2",
      ic: 0.015,
      turnover: 0.88,
      drawdown: -0.18,
      allocation: 0.2,
    },
  ];
}
