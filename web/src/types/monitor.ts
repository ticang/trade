export interface Position {
  account_id: string;
  symbol: string;
  name: string;
  qty: number;
  avg_cost: number;
  last: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  weight: number;
}

export type StrategyStatus =
  | "draft"
  | "backtested"
  | "paper"
  | "approved"
  | "live"
  | "monitoring"
  | "degraded"
  | "offline";

export interface Strategy {
  name: string;
  status: StrategyStatus;
  account_id: string;
  ic: number;
  turnover: number;
  drawdown: number;
  allocation: number;
}

export interface RiskState {
  total_position_pct: number;
  max_single_pct: number;
  industry_exposure: { industry: string; pct: number }[];
  drawdown: number;
  drawdown_limit: number;
  circuit_breaker: "normal" | "degraded" | "halted";
}

export type AlertLevel = "info" | "warn" | "error";

export interface Alert {
  ts: number;
  level: AlertLevel;
  title: string;
  detail: string;
}
