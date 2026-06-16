"use client";

import { useState } from "react";
import { TradePanel } from "@/components/trade/TradePanel";
import { PositionsTable } from "@/components/monitor/PositionsTable";
import { OrdersList } from "@/components/trade/OrdersList";
import { FillsList } from "@/components/trade/FillsList";
import { usePositions } from "@/hooks/usePositions";
import { useOrders } from "@/hooks/useOrders";
import { useFills } from "@/hooks/useFills";
import type { Order, OrderSide } from "@/types/trade";
import { QueryState } from "@/components/ui/QueryState";

const SYMBOL = "000001";

export function TradeDashboard() {
  const positions = usePositions();
  const orders = useOrders();
  const fills = useFills();

  const [localOrders, setLocalOrders] = useState<Order[]>([]);
  const [note, setNote] = useState<string | null>(null);

  const onSubmit = ({ side, price, qty }: { side: OrderSide; price: number; qty: number }) => {
    const order: Order = {
      order_id: `local-${Date.now()}`,
      account_id: "acct1",
      symbol: SYMBOL,
      side,
      price,
      qty,
      filled_qty: 0,
      status: "pending",
      ts: Date.now(),
    };
    setLocalOrders((prev) => [order, ...prev]);
    setNote(`模拟下单: ${side === "buy" ? "买" : "卖"} ${SYMBOL} ${qty}@${price}`);
  };

  return (
    <div className="space-y-lg">
      <h1 className="text-title-lg text-on-dark">交易终端</h1>

      <TradePanel symbol={SYMBOL} onSubmit={onSubmit} />

      {note && (
        <div
          data-testid="mock-order-note"
          className="bg-surface-elevated-dark text-info rounded-md px-md py-sm text-body-md"
        >
          {note}
        </div>
      )}

      <QueryState label="持仓" isLoading={positions.isLoading} isError={positions.isError} isEmpty={!positions.isLoading && !positions.isError && (positions.data?.length ?? 0) === 0} error={positions.error} />
      <PositionsTable rows={positions.data ?? []} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-lg">
        <div className="space-y-sm">
          <QueryState label="委托" isLoading={orders.isLoading} isError={orders.isError} isEmpty={!orders.isLoading && !orders.isError && localOrders.length === 0 && (orders.data?.length ?? 0) === 0} error={orders.error} />
          <OrdersList orders={[...localOrders, ...(orders.data ?? [])]} />
        </div>
        <div className="space-y-sm">
          <QueryState label="成交" isLoading={fills.isLoading} isError={fills.isError} isEmpty={!fills.isLoading && !fills.isError && (fills.data?.length ?? 0) === 0} error={fills.error} />
          <FillsList fills={fills.data ?? []} />
        </div>
      </div>
    </div>
  );
}
