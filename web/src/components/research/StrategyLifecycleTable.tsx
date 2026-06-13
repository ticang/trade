"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LifecycleBadge } from "@/components/monitor/LifecycleBadge";
import { StrategyLifecycleEntry } from "@/types/research";

interface Props {
  rows: StrategyLifecycleEntry[];
}

// Local-only mock transition targets. The real backend approval/degrade flow
// is out of scope for the UI; these mutate an in-memory copy for demo.
const TRANSITION: Partial<Record<string, { label: string; variant: "primary" | "trading-down"; next: string }>> = {
  paper: { label: "审批上线", variant: "primary", next: "approved" },
  live: { label: "降级", variant: "trading-down", next: "degraded" },
};

export function StrategyLifecycleTable({ rows }: Props) {
  const [local, setLocal] = useState<StrategyLifecycleEntry[]>(rows);

  const onClick = (name: string, next: string) => {
    setLocal((prev) =>
      prev.map((e) =>
        e.name === name
          ? {
              ...e,
              status: next as StrategyLifecycleEntry["status"],
              // Set a sensible approval/degrade footprint when transitioning.
              approved_by: next === "approved" ? "local-demo" : e.approved_by,
              degraded_reason:
                next === "degraded" ? "Local demo degrade" : e.degraded_reason,
            }
          : e,
      ),
    );
  };

  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="flex items-baseline justify-between pb-sm">
        <h3 className="text-title-md text-body">策略生命周期</h3>
        <span className="text-caption text-muted">mock · 本地流转</span>
      </div>

      <div className="grid grid-cols-12 gap-md border-b border-hairline-ondark pb-sm text-muted text-body-md">
        <span className="col-span-3">策略</span>
        <span className="col-span-2">状态</span>
        <span className="col-span-2 text-right">OOS IC</span>
        <span className="col-span-2">审批人</span>
        <span className="col-span-2">降级原因</span>
        <span className="col-span-1 text-right">操作</span>
      </div>

      {local.map((e) => {
        const action = TRANSITION[e.status];
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
            <div className="col-span-1 flex justify-end">
              {action ? (
                <Button
                  variant={action.variant}
                  data-testid={`lifecycle-action-${e.name}`}
                  className="px-3 py-1 h-7 text-caption"
                  onClick={() => onClick(e.name, action.next)}
                >
                  {action.label}
                </Button>
              ) : null}
            </div>
          </div>
        );
      })}
    </Card>
  );
}
