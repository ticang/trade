import { RiskState } from "@/types/monitor";

// Deterministic aggregate risk state.
export function mockRisk(): RiskState {
  return {
    total_position_pct: 0.62,
    max_single_pct: 0.32,
    industry_exposure: [
      { industry: "白酒", pct: 0.32 },
      { industry: "新能源", pct: 0.19 },
      { industry: "银行", pct: 0.11 },
    ],
    drawdown: -0.08,
    drawdown_limit: -0.15,
    circuit_breaker: "normal",
  };
}
