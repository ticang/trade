"use client";
import { StatCard } from "@/components/ui/StatCard";
import { usePositions } from "@/hooks/usePositions";
import { useStrategies } from "@/hooks/useStrategies";
import { StrategyStatus } from "@/types/monitor";

const ACTIVE_STATUS: ReadonlySet<StrategyStatus> = new Set([
  "live",
  "paper",
  "monitoring",
]);

const directionOf = (v: number): "up" | "down" | "flat" =>
  v > 0 ? "up" : v < 0 ? "down" : "flat";

const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toLocaleString()}`;

export function PnlOverview() {
  const positions = usePositions();
  const strategies = useStrategies();

  const rows = positions.data ?? [];
  const totalAssets = rows.reduce((sum, p) => sum + p.market_value, 0);
  const dailyPnl = rows.reduce((sum, p) => sum + p.pnl, 0);
  // Cumulative P&L is a mocked positive snapshot (no historical cost basis in mock).
  const cumulativePnl = 28640;
  const activeStrategies = (strategies.data ?? []).filter((s) =>
    ACTIVE_STATUS.has(s.status),
  ).length;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-md">
      <StatCard label="总资产" value={`¥${Math.round(totalAssets).toLocaleString()}`} />
      <StatCard
        label="当日盈亏"
        value={`¥${signed(Math.round(dailyPnl))}`}
        direction={directionOf(dailyPnl)}
      />
      <StatCard
        label="累计盈亏"
        value={`¥${signed(cumulativePnl)}`}
        direction="up"
      />
      <StatCard label="运行策略数" value={String(activeStrategies)} direction="flat" />
    </div>
  );
}
