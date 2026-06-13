"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { Button } from "@/components/ui/Button";
import type { OrderSide } from "@/types/trade";

interface OrderFormProps {
  symbol: string;
  available: number;
  onSubmit: (order: { side: OrderSide; price: number; qty: number }) => void;
}

const QUICK_PCT = [25, 50, 75, 100];

export function OrderForm({ symbol, available, onSubmit }: OrderFormProps) {
  const [side, setSide] = useState<OrderSide>("buy");
  const [price, setPrice] = useState<number>(0);
  const [qty, setQty] = useState<number>(0);

  const amount = price * qty;

  const applyQuick = (pct: number) => {
    if (price <= 0) return;
    setQty(Math.floor((available * pct) / 100 / price));
  };

  const submit = () => {
    if (price <= 0 || qty <= 0) return;
    onSubmit({ side, price, qty });
  };

  return (
    <div className="bg-surface-card-dark text-on-dark rounded-lg p-md flex flex-col gap-md">
      <div className="flex items-center justify-between">
        <span className="text-title-sm font-display">{symbol}</span>
        <span className="text-number-sm font-number text-muted">
          可用 {available.toLocaleString()}
        </span>
      </div>

      <div role="tablist" className="grid grid-cols-2 gap-xs">
        <button
          type="button"
          role="tab"
          aria-selected={side === "buy"}
          onClick={() => setSide("buy")}
          className={clsx(
            "rounded-sm py-2 text-button font-display",
            side === "buy" ? "bg-trading-up text-on-dark" : "bg-surface-elevated-dark text-muted",
          )}
        >
          买入
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={side === "sell"}
          onClick={() => setSide("sell")}
          className={clsx(
            "rounded-sm py-2 text-button font-display",
            side === "sell" ? "bg-trading-down text-on-dark" : "bg-surface-elevated-dark text-muted",
          )}
        >
          卖出
        </button>
      </div>

      <label className="flex flex-col gap-xxs text-caption text-muted">
        价格
        <input
          type="number"
          aria-label="价格"
          value={price === 0 ? "" : price}
          onChange={(e) => setPrice(Number(e.target.value))}
          className="bg-surface-card-dark text-on-dark rounded-md px-sm py-2 font-number text-number-md outline-none ring-1 ring-hairline-ondark focus:ring-trading-up"
        />
      </label>

      <label className="flex flex-col gap-xxs text-caption text-muted">
        数量
        <input
          type="number"
          aria-label="数量"
          value={qty === 0 ? "" : qty}
          onChange={(e) => setQty(Number(e.target.value))}
          className="bg-surface-card-dark text-on-dark rounded-md px-sm py-2 font-number text-number-md outline-none ring-1 ring-hairline-ondark focus:ring-trading-up"
        />
      </label>

      <div className="grid grid-cols-4 gap-xxs">
        {QUICK_PCT.map((pct) => (
          <button
            key={pct}
            type="button"
            onClick={() => applyQuick(pct)}
            className="bg-surface-elevated-dark text-on-dark rounded-xs py-1 text-caption font-display"
          >
            {pct}%
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between border-t border-hairline-ondark pt-sm">
        <span className="text-caption text-muted">预估金额</span>
        <span data-testid="order-preview-amount" className="font-number text-number-md text-on-dark">
          {amount}
        </span>
      </div>

      <Button
        variant={side === "buy" ? "trading-up" : "trading-down"}
        onClick={submit}
        className="w-full"
      >
        {side === "buy" ? "买入" : "卖出"}
      </Button>
    </div>
  );
}
