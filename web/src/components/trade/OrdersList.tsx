import { clsx } from "clsx";
import { Card } from "@/components/ui/Card";
import { PriceCell } from "@/components/ui/PriceCell";
import type { Order, OrderSide, OrderStatus } from "@/types/trade";

export interface OrdersListProps {
  orders: Order[];
}

const STATUS_COLOR: Record<OrderStatus, string> = {
  filled: "text-trading-up",
  partial_filled: "text-primary",
  submitted: "text-info",
  pending: "text-info",
  cancelled: "text-muted",
  rejected: "text-muted",
};

const SIDE_COLOR: Record<OrderSide, string> = {
  buy: "text-trading-up",
  sell: "text-trading-down",
};

const SIDE_LABEL: Record<OrderSide, string> = { buy: "买入", sell: "卖出" };

const numFmt = (v: number) => v.toLocaleString();

function tsFmt(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function OrdersList({ orders }: OrdersListProps) {
  const sorted = [...orders].sort((a, b) => b.ts - a.ts);

  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="grid grid-cols-7 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>标的</span>
        <span>方向</span>
        <span className="text-right">价格</span>
        <span className="text-right">数量</span>
        <span className="text-right">已成</span>
        <span>状态</span>
        <span className="text-right">时间</span>
      </div>
      {sorted.length === 0 ? (
        <div className="py-md text-caption text-muted">暂无委托</div>
      ) : (
        sorted.map((o) => (
          <div
            key={o.order_id}
            data-testid="order-row"
            data-order-id={o.order_id}
            className="grid grid-cols-7 gap-md py-sm items-center border-b border-hairline-ondark last:border-0"
          >
            <span className="font-number text-number-md">{o.symbol}</span>
            <span
              data-testid={`order-side-${o.side}`}
              className={clsx("text-body-md", SIDE_COLOR[o.side])}
            >
              {SIDE_LABEL[o.side]}
            </span>
            <span className="text-right">
              <PriceCell value={o.price} direction="flat" format={numFmt} />
            </span>
            <span className="text-right font-number text-number-md">
              {numFmt(o.qty)}
            </span>
            <span className="text-right font-number text-number-md text-muted">
              {numFmt(o.filled_qty)}
            </span>
            <span
              data-testid={`order-status-${o.status}`}
              className={clsx("text-body-md", STATUS_COLOR[o.status])}
            >
              {o.status}
            </span>
            <span className="text-right text-caption text-muted font-number">
              {tsFmt(o.ts)}
            </span>
          </div>
        ))
      )}
    </Card>
  );
}
