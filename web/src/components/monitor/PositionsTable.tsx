import { PriceCell } from "@/components/ui/PriceCell";
import { Position } from "@/types/monitor";

export interface PositionsTableProps {
  rows: Position[];
}

const pnlFmt = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
const pctFmt = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const numFmt = (v: number) => v.toFixed(2);
const qtyFmt = (v: number) => v.toLocaleString();

const directionOf = (v: number): "up" | "down" | "flat" =>
  v > 0 ? "up" : v < 0 ? "down" : "flat";

export function PositionsTable({ rows }: PositionsTableProps) {
  // Group by account_id preserving ascending account order.
  const groups = new Map<string, Position[]>();
  for (const r of rows) {
    const list = groups.get(r.account_id);
    if (list) list.push(r);
    else groups.set(r.account_id, [r]);
  }
  const accountIds = [...groups.keys()].sort();

  return (
    <div className="bg-surface-card-dark rounded-xl p-lg text-on-dark">
      <div className="grid grid-cols-8 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>账户</span>
        <span>标的</span>
        <span className="text-right">数量</span>
        <span className="text-right">成本</span>
        <span className="text-right">现价</span>
        <span className="text-right">市值</span>
        <span className="text-right">盈亏</span>
        <span className="text-right">权重</span>
      </div>
      {accountIds.map((acct) => {
        const items = groups.get(acct)!;
        return (
          <div key={acct} className="border-b border-hairline-ondark last:border-0">
            <div
              data-testid="account-group"
              className="py-xs text-caption text-muted"
            >
              {acct}
            </div>
            {items.map((p) => {
              const dir = directionOf(p.pnl);
              return (
                <div
                  key={`${p.account_id}-${p.symbol}`}
                  className="grid grid-cols-8 gap-md py-sm items-center"
                >
                  <span className="text-caption text-muted">{p.account_id}</span>
                  <div className="flex flex-col">
                    <span className="font-number text-number-md">{p.symbol}</span>
                    <span className="text-caption text-muted">{p.name}</span>
                  </div>
                  <span className="text-right font-number text-number-md">
                    {qtyFmt(p.qty)}
                  </span>
                  <span className="text-right font-number text-number-md text-muted">
                    {numFmt(p.avg_cost)}
                  </span>
                  <span className="text-right font-number text-number-md">
                    {numFmt(p.last)}
                  </span>
                  <span className="text-right font-number text-number-md">
                    {Math.round(p.market_value).toLocaleString()}
                  </span>
                  <div className="text-right">
                    <PriceCell value={p.pnl} direction={dir} format={pnlFmt} />
                    <div>
                      <PriceCell value={p.pnl_pct / 100} direction={dir} format={pctFmt} />
                    </div>
                  </div>
                  <span className="text-right font-number text-number-md text-muted">
                    {(p.weight * 100).toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
