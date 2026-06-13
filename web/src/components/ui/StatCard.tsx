import { clsx } from "clsx";
import { Card } from "@/components/ui/Card";

export interface StatCardProps {
  label: string;
  value: string;
  direction?: "up" | "down" | "flat";
}

const COLOR: Record<NonNullable<StatCardProps["direction"]>, string> = {
  up: "text-trading-up",
  down: "text-trading-down",
  flat: "text-muted",
};

export function StatCard({ label, value, direction = "flat" }: StatCardProps) {
  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="text-caption text-muted">{label}</div>
      <div className={clsx("font-number text-number-display pt-xs", COLOR[direction])}>
        {value}
      </div>
    </Card>
  );
}
