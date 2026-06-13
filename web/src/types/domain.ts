export interface Bar {
  ts: number; // unix ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SentimentPoint {
  ts: number;
  score: number; // [-1, 1]
}

export type SignalDirection = "buy" | "sell" | "warn";
export interface ReplaySignal {
  ts: number;
  direction: SignalDirection;
  label: string; // e.g. "CPO 起飞", "抄底", "清仓"
  price: number;
}

export interface MarketRow {
  symbol: string;
  name: string;
  last: number;
  change: number;
  volume: number;
}
