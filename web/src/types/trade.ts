export type OrderSide = "buy" | "sell";

export type OrderStatus =
  | "pending"
  | "submitted"
  | "partial_filled"
  | "filled"
  | "cancelled"
  | "rejected";

export interface Order {
  order_id: string;
  account_id: string;
  symbol: string;
  side: OrderSide;
  price: number;
  qty: number;
  filled_qty: number;
  status: OrderStatus;
  ts: number;
}

export interface Fill {
  fill_id: string;
  order_id: string;
  symbol: string;
  side: OrderSide;
  price: number;
  qty: number;
  ts: number;
}

export interface AccountSnapshot {
  account_id: string;
  cash: number;
  market_value: number;
  total: number;
  available: number;
}
