"use client";

import { StatCard } from "@/components/ui/StatCard";
import { KlineChart } from "@/components/charts/KlineChart";
import { OrderForm } from "@/components/trade/OrderForm";
import { useKline } from "@/hooks/useKline";
import { useAccount } from "@/hooks/useAccount";
import type { OrderSide } from "@/types/trade";

interface TradePanelProps {
  symbol: string;
  accountId?: string;
  onSubmit: (order: { side: OrderSide; price: number; qty: number }) => void;
}

const num = (v: number) => Math.round(v).toLocaleString();

export function TradePanel({ symbol, accountId = "acct1", onSubmit }: TradePanelProps) {
  const kline = useKline(symbol);
  const accounts = useAccount();
  const acct = accounts.data?.find((a) => a.account_id === accountId);

  return (
    <div className="space-y-lg">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-lg">
        <StatCard label="总资产" value={num(acct?.total ?? 0)} direction="flat" />
        <StatCard label="可用" value={num(acct?.available ?? 0)} direction="flat" />
        <StatCard label="持仓市值" value={num(acct?.market_value ?? 0)} direction="flat" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-lg">
        <div className="lg:col-span-2 bg-surface-card-dark rounded-lg p-lg">
          {kline.data && <KlineChart bars={kline.data} />}
        </div>
        <div className="lg:col-span-1">
          <OrderForm symbol={symbol} available={acct?.available ?? 0} onSubmit={onSubmit} />
        </div>
      </div>
    </div>
  );
}
