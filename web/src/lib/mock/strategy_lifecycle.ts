import { StrategyLifecycleEntry } from "@/types/research";

// Deterministic lifecycle entries spanning representative statuses.
export function mockStrategyLifecycle(): StrategyLifecycleEntry[] {
  return [
    {
      name: "multi_factor_alpha_v3",
      status: "live",
      oos_ic: 0.094,
      approved_by: "wk",
      degraded_reason: null,
    },
    {
      name: "earnings_surprise_v2",
      status: "paper",
      oos_ic: 0.101,
      approved_by: null,
      degraded_reason: null,
    },
    {
      name: "intraday_reversal",
      status: "degraded",
      oos_ic: 0.038,
      approved_by: "wk",
      degraded_reason: "OOS IC dropped below 0.05 threshold for 5 sessions",
    },
    {
      name: "vol_carry_experiment",
      status: "draft",
      oos_ic: 0.012,
      approved_by: null,
      degraded_reason: null,
    },
  ];
}
