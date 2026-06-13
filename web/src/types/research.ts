import { StrategyStatus } from "@/types/monitor";

export interface FactorEval {
  name: string;
  ic_series: { ts: number; ic: number }[];
  ic: number;
  ir: number;
  turnover: number;
  // Long-short annualized return per quantile decile (10 buckets, low to high).
  quantile_returns: number[];
  // Correlation with known/established factors; lower is more novel.
  novelty_corr: number;
}

export interface BacktestPoint {
  ts: number;
  equity: number;
  drawdown: number;
  benchmark: number;
}

export interface BacktestResult {
  strategy: string;
  series: BacktestPoint[];
  annual_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  turnover: number;
  attribution: { factor: string; contribution: number }[];
}

export interface StrategyLifecycleEntry {
  name: string;
  status: StrategyStatus;
  oos_ic: number;
  approved_by: string | null;
  degraded_reason: string | null;
}
