"use client";

import { TradePanel } from "@/components/trade/TradePanel";
import { PositionsTable } from "@/components/monitor/PositionsTable";
import { OrdersList } from "@/components/trade/OrdersList";
import { FillsList } from "@/components/trade/FillsList";
import { usePositions } from "@/hooks/usePositions";
import { useOrders } from "@/hooks/useOrders";
import { useFills } from "@/hooks/useFills";
import type { OrderSide } from "@/types/trade";
import { QueryState } from "@/components/ui/QueryState";

const SYMBOL = "600000";
const SUBMIT_DISABLED_REASON = "只读运行态已接通；下单需等待 broker POST 与实盘风控放行";

export function TradeDashboard() {
  const positions = usePositions();
  const orders = useOrders();
  const fills = useFills();

  const onSubmit = (_order: { side: OrderSide; price: number; qty: number }) => {
    return;
  };

  return (
    <div className="space-y-lg">
      <h1 className="text-title-lg text-on-dark">交易终端</h1>

      <TradePanel symbol={SYMBOL} onSubmit={onSubmit} submitDisabledReason={SUBMIT_DISABLED_REASON} />

      <QueryState label="持仓" isLoading={positions.isLoading} isError={positions.isError} isEmpty={!positions.isLoading && !positions.isError && (positions.data?.length ?? 0) === 0} error={positions.error} />
      <PositionsTable rows={positions.data ?? []} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-lg">
        <div className="space-y-sm">
          <QueryState label="委托" isLoading={orders.isLoading} isError={orders.isError} isEmpty={!orders.isLoading && !orders.isError && (orders.data?.length ?? 0) === 0} error={orders.error} />
          <OrdersList orders={orders.data ?? []} />
        </div>
        <div className="space-y-sm">
          <QueryState label="成交" isLoading={fills.isLoading} isError={fills.isError} isEmpty={!fills.isLoading && !fills.isError && (fills.data?.length ?? 0) === 0} error={fills.error} />
          <FillsList fills={fills.data ?? []} />
        </div>
      </div>
    </div>
  );
}
