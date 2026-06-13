import { clsx } from "clsx";
import { Card } from "@/components/ui/Card";
import { PriceCell } from "@/components/ui/PriceCell";
import type { Fill, OrderSide } from "@/types/trade";

export interface FillsListProps {
  fills: Fill[];
}

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

export function FillsList({ fills }: FillsListProps) {
  const sorted = [...fills].sort((a, b) => b.ts - a.ts);

  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="grid grid-cols-5 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>标的</span>
        <span>方向</span>
        <span className="text-right">价格</span>
        <span className="text-right">数量</span>
        <span className="text-right">时间</span>
      </div>
      {sorted.length === 0 ? (
        <div className="py-md text-caption text-muted">暂无成交</div>
      ) : (
        sorted.map((f) => (
          <div
            key={f.fill_id}
            data-testid="fill-row"
            data-fill-id={f.fill_id}
            className="grid grid-cols-5 gap-md py-sm items-center border-b border-hairline-ondark last:border-0"
          >
            <span className="font-number text-number-md">{f.symbol}</span>
            <span
              data-testid={`fill-side-${f.side}`}
              className={clsx("text-body-md", SIDE_COLOR[f.side])}
            >
              {SIDE_LABEL[f.side]}
            </span>
            <span className="text-right">
              <PriceCell value={f.price} direction="flat" format={numFmt} />
            </span>
            <span className="text-right font-number text-number-md">
              {numFmt(f.qty)}
            </span>
            <span className="text-right text-caption text-muted font-number">
              {tsFmt(f.ts)}
            </span>
          </div>
        ))
      )}
    </Card>
  );
}
