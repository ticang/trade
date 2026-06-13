import { clsx } from "clsx";
import { Card } from "@/components/ui/Card";
import { Alert, AlertLevel } from "@/types/monitor";

export interface AlertListProps {
  alerts: Alert[];
}

const LEVEL_COLOR: Record<AlertLevel, string> = {
  error: "text-trading-down",
  warn: "text-primary",
  info: "text-muted",
};

const LEVEL_BG: Record<AlertLevel, string> = {
  error: "bg-trading-down",
  warn: "bg-primary",
  info: "bg-muted",
};

// Coarse relative time for an alert ts (hours/days ago).
function relativeTime(ts: number): string {
  const diffMs = Date.now() - ts;
  const hours = Math.round(diffMs / 3600_000);
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  return `${days} 天前`;
}

export function AlertList({ alerts }: AlertListProps) {
  // Feed is already newest-first; preserve order.
  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="pb-sm border-b border-hairline-ondark text-title-sm">
        告警
      </div>
      {alerts.length === 0 ? (
        <div className="py-md text-caption text-muted">暂无告警</div>
      ) : (
        <div className="flex flex-col">
          {alerts.map((a, idx) => (
            <div
              key={`${a.ts}-${idx}`}
              data-level={a.level}
              className="flex items-start gap-sm py-sm border-b border-hairline-ondark last:border-0"
            >
              <span
                className={clsx(
                  "mt-xxs inline-block h-xxs w-xxs shrink-0 rounded-pill",
                  LEVEL_BG[a.level],
                )}
              />
              <div className="flex flex-1 flex-col">
                <span
                  className={clsx("text-body-md", LEVEL_COLOR[a.level])}
                >
                  {a.title}
                </span>
                <span className="text-caption text-muted">{a.detail}</span>
              </div>
              <span className="shrink-0 text-caption text-muted">
                {relativeTime(a.ts)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
