"use client";
import { PnlOverview } from "@/components/monitor/PnlOverview";
import { PositionsTable } from "@/components/monitor/PositionsTable";
import { StrategyTable } from "@/components/monitor/StrategyTable";
import { RiskPanel } from "@/components/monitor/RiskPanel";
import { AlertList } from "@/components/monitor/AlertList";
import { usePositions } from "@/hooks/usePositions";
import { useStrategies } from "@/hooks/useStrategies";
import { useRisk } from "@/hooks/useRisk";
import { useAlerts } from "@/hooks/useAlerts";

export function MonitorDashboard() {
  const positions = usePositions();
  const strategies = useStrategies();
  const risk = useRisk();
  const alerts = useAlerts();

  return (
    <div className="space-y-lg">
      <h1 className="text-title-lg text-on-dark">监控面板</h1>

      <PnlOverview />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-lg">
        <div className="lg:col-span-2">
          <PositionsTable rows={positions.data ?? []} />
        </div>
        <div className="lg:col-span-1">
          {risk.data && <RiskPanel state={risk.data} />}
        </div>
      </div>

      <StrategyTable rows={strategies.data ?? []} />

      <AlertList alerts={alerts.data ?? []} />
    </div>
  );
}
