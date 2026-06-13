import { PriceCell } from "@/components/ui/PriceCell";
import { LifecycleBadge } from "@/components/monitor/LifecycleBadge";
import { Strategy } from "@/types/monitor";

export interface StrategyTableProps {
  rows: Strategy[];
}

const directionOf = (v: number): "up" | "down" | "flat" =>
  v > 0 ? "up" : v < 0 ? "down" : "flat";

const pctFmt = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const drawdownFmt = (v: number) => `${(v * 100).toFixed(2)}%`;

export function StrategyTable({ rows }: StrategyTableProps) {
  return (
    <div className="bg-surface-card-dark rounded-xl p-lg text-on-dark">
      <div className="grid grid-cols-6 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>策略</span>
        <span>状态</span>
        <span className="text-right">IC</span>
        <span className="text-right">换手</span>
        <span className="text-right">回撤</span>
        <span className="text-right">配比</span>
      </div>
      {rows.map((s) => {
        const icDir = directionOf(s.ic);
        const ddDir = directionOf(s.drawdown);
        return (
          <div
            key={`${s.account_id}-${s.name}`}
            className="grid grid-cols-6 gap-md py-sm items-center border-b border-hairline-ondark last:border-0"
          >
            <div className="flex flex-col">
              <span className="text-body-md">{s.name}</span>
              <span className="text-caption text-muted">{s.account_id}</span>
            </div>
            <LifecycleBadge status={s.status} />
            <div className="text-right">
              <PriceCell value={s.ic} direction={icDir} format={pctFmt} />
            </div>
            <span className="text-right font-number text-number-md text-muted">
              {s.turnover.toFixed(2)}
            </span>
            <div className="text-right">
              <PriceCell value={s.drawdown} direction={ddDir} format={drawdownFmt} />
            </div>
            <span className="text-right font-number text-number-md text-muted">
              {(s.allocation * 100).toFixed(0)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
