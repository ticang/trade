import { clsx } from "clsx";
import { StrategyStatus } from "@/types/monitor";

const STATUS_COLOR: Record<StrategyStatus, string> = {
  live: "text-trading-up",
  paper: "text-primary",
  degraded: "text-trading-down",
  offline: "text-muted",
  draft: "text-info",
  backtested: "text-info",
  approved: "text-info",
  monitoring: "text-info",
};

const STATUS_BG: Record<StrategyStatus, string> = {
  live: "bg-trading-up/10",
  paper: "bg-primary/10",
  degraded: "bg-trading-down/10",
  offline: "bg-muted/10",
  draft: "bg-info/10",
  backtested: "bg-info/10",
  approved: "bg-info/10",
  monitoring: "bg-info/10",
};

export interface LifecycleBadgeProps {
  status: StrategyStatus;
}

export function LifecycleBadge({ status }: LifecycleBadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-sm px-xs text-caption",
        STATUS_COLOR[status],
        STATUS_BG[status],
      )}
    >
      {status}
    </span>
  );
}
