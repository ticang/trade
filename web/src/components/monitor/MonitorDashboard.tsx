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
import { QueryState } from "@/components/ui/QueryState";

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
          <QueryState label="持仓" isLoading={positions.isLoading} isError={positions.isError} isEmpty={!positions.isLoading && !positions.isError && (positions.data?.length ?? 0) === 0} error={positions.error} />
          <PositionsTable rows={positions.data ?? []} />
        </div>
        <div className="lg:col-span-1">
          <QueryState label="风险" isLoading={risk.isLoading} isError={risk.isError} isEmpty={!risk.isLoading && !risk.isError && !risk.data} error={risk.error} />
          {risk.data && <RiskPanel state={risk.data} />}
        </div>
      </div>

      <QueryState label="策略" isLoading={strategies.isLoading} isError={strategies.isError} isEmpty={!strategies.isLoading && !strategies.isError && (strategies.data?.length ?? 0) === 0} error={strategies.error} />
      <StrategyTable rows={strategies.data ?? []} />

      <QueryState label="告警" isLoading={alerts.isLoading} isError={alerts.isError} isEmpty={!alerts.isLoading && !alerts.isError && (alerts.data?.length ?? 0) === 0} error={alerts.error} />
      <AlertList alerts={alerts.data ?? []} />
    </div>
  );
}
