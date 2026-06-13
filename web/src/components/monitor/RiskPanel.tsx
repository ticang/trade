import { clsx } from "clsx";
import { Card } from "@/components/ui/Card";
import { RiskState } from "@/types/monitor";

export interface RiskPanelProps {
  state: RiskState;
}

type CircuitBreaker = RiskState["circuit_breaker"];

const CB_LABEL: Record<CircuitBreaker, string> = {
  normal: "正常",
  degraded: "降级",
  halted: "熔断",
};

const CB_COLOR: Record<CircuitBreaker, string> = {
  normal: "text-trading-up",
  degraded: "text-primary",
  halted: "text-trading-down",
};

const CB_BG: Record<CircuitBreaker, string> = {
  normal: "bg-trading-up/10",
  degraded: "bg-primary/10",
  halted: "bg-trading-down/10",
};

const pctFmt = (v: number) => `${(v * 100).toFixed(1)}%`;

export function RiskPanel({ state }: RiskPanelProps) {
  // drawdown vs limit: fill proportional to |drawdown| / |limit|.
  const drawdownRatio = Math.min(
    1,
    Math.abs(state.drawdown) / Math.abs(state.drawdown_limit),
  );

  return (
    <Card variant="surface-dark" className="p-lg">
      <div className="pb-sm border-b border-hairline-ondark text-title-sm">
        风控面板
      </div>

      <div className="grid grid-cols-2 gap-md pt-sm">
        <div className="flex flex-col">
          <span className="text-caption text-muted">总仓位</span>
          <span className="font-number text-number-md">
            {pctFmt(state.total_position_pct)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-caption text-muted">单票上限</span>
          <span className="font-number text-number-md">
            {pctFmt(state.max_single_pct)}
          </span>
        </div>
      </div>

      <div className="pt-sm">
        <div className="flex items-center justify-between text-caption text-muted pb-xs">
          <span>回撤</span>
          <span className="font-number text-trading-down">
            {(state.drawdown * 100).toFixed(2)}%
          </span>
        </div>
        <div className="h-xs w-full rounded-xs bg-surface-elevated-dark">
          <div
            data-testid="drawdown-bar"
            className="h-full rounded-xs bg-trading-down"
            style={{ width: `${drawdownRatio * 100}%` }}
          />
        </div>
        <div className="text-caption text-muted pt-xs">
          限制 {(state.drawdown_limit * 100).toFixed(2)}%
        </div>
      </div>

      <div className="pt-sm">
        <span className="text-caption text-muted">熔断状态</span>
        <div className="pt-xs">
          <span
            className={clsx(
              "inline-flex items-center rounded-sm px-xs text-caption",
              CB_COLOR[state.circuit_breaker],
              CB_BG[state.circuit_breaker],
            )}
          >
            {CB_LABEL[state.circuit_breaker]}
          </span>
        </div>
      </div>

      <div className="pt-sm">
        <span className="text-caption text-muted">行业暴露</span>
        <div className="pt-xs flex flex-col gap-xs">
          {state.industry_exposure.map((row) => (
            <div key={row.industry} className="flex items-center gap-sm">
              <span className="w-12 shrink-0 text-caption text-muted">
                {row.industry}
              </span>
              <div className="h-xxs flex-1 rounded-xs bg-surface-elevated-dark">
                <div
                  className="h-full rounded-xs bg-primary"
                  style={{ width: `${Math.min(100, row.pct * 100)}%` }}
                />
              </div>
              <span className="w-10 shrink-0 text-right font-number text-number-sm">
                {(row.pct * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
