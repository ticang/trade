import { Card } from "@/components/ui/Card";
import { LifecycleBadge } from "@/components/monitor/LifecycleBadge";
import { StrategyLifecycleEntry } from "@/types/research";

interface Props {
  rows: StrategyLifecycleEntry[];
}

export function StrategyLifecycleTable({ rows }: Props) {
  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="flex items-baseline justify-between pb-sm">
        <h3 className="text-title-md text-body">策略生命周期</h3>
        <span className="text-caption text-muted">runtime state</span>
      </div>

      <div className="grid grid-cols-12 gap-md border-b border-hairline-ondark pb-sm text-muted text-body-md">
        <span className="col-span-3">策略</span>
        <span className="col-span-2">状态</span>
        <span className="col-span-2 text-right">OOS IC</span>
        <span className="col-span-2">审批人</span>
        <span className="col-span-2">降级原因</span>
        <span className="col-span-1 text-right">操作</span>
      </div>

      {rows.map((e) => {
        const icColor = e.oos_ic >= 0 ? "text-trading-up" : "text-trading-down";
        return (
          <div
            key={e.name}
            data-testid="lifecycle-row"
            className="grid grid-cols-12 gap-md py-sm items-center border-b border-hairline-ondark last:border-0"
          >
            <span className="col-span-3 font-number text-number-md">{e.name}</span>
            <div className="col-span-2">
              <LifecycleBadge status={e.status} />
            </div>
            <span className={`col-span-2 text-right font-number text-number-md ${icColor}`}>
              {e.oos_ic.toFixed(3)}
            </span>
            <span className="col-span-2 text-body-md text-muted">
              {e.approved_by ?? "—"}
            </span>
            <span className="col-span-2 text-caption text-muted truncate" title={e.degraded_reason ?? ""}>
              {e.degraded_reason ?? "—"}
            </span>
            <span className="col-span-1 text-right text-caption text-muted">只读</span>
          </div>
        );
      })}
    </Card>
  );
}
