"use client";
import { clsx } from "clsx";
import { LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { Card } from "@/components/ui/Card";
import { FactorEval } from "@/types/research";
import { theme } from "@/lib/theme";

interface Props {
  factor: FactorEval;
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-caption text-muted">{label}</span>
      <span className="font-number text-number-sm pt-1">{children}</span>
    </div>
  );
}

// Quantile decile bar: height proportional to |value|, colored by sign.
function QuantileBar({ value, maxAbs }: { value: number; maxAbs: number }) {
  const heightPct = maxAbs > 0 ? Math.max(4, (Math.abs(value) / maxAbs) * 100) : 4;
  const positive = value >= 0;
  return (
    <div className="flex h-full flex-1 flex-col justify-center" title={`${value}`}>
      <div className="flex h-full w-full items-center justify-center">
        <div
          data-testid="quantile-bar"
          style={{
            height: `${heightPct}%`,
            backgroundColor: positive ? theme.colors.tradingUp : theme.colors.tradingDown,
          }}
          className="w-full min-h-[4px] rounded-sm"
        />
      </div>
    </div>
  );
}

export function FactorEvalChart({ factor }: Props) {
  const icPositive = factor.ic >= 0;
  const icColor = icPositive ? "text-trading-up" : "text-trading-down";
  const maxAbs = Math.max(...factor.quantile_returns.map((v) => Math.abs(v)), 1e-9);

  return (
    <Card variant="surface-dark" className="p-lg">
      {/* Header: factor name + metric row */}
      <div className="flex flex-wrap items-end justify-between gap-md">
        <h3 className="text-title-md text-body">{factor.name}</h3>
        <div className="flex gap-lg">
          <Metric label="IC">
            <span data-testid="factor-ic-value" className={icColor}>
              {factor.ic.toFixed(3)}
            </span>
          </Metric>
          <Metric label="IR">{factor.ir.toFixed(2)}</Metric>
          <Metric label="Turnover">{factor.turnover.toFixed(2)}</Metric>
          <Metric label="Novelty">{factor.novelty_corr.toFixed(2)}</Metric>
        </div>
      </div>

      {/* IC time-series line chart */}
      <div data-testid="factor-ic-chart" className="mt-md h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={factor.ic_series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <XAxis dataKey="ts" tick={false} axisLine={{ stroke: theme.colors.hairlineOnDark }} />
            <YAxis
              tick={{ fill: theme.colors.muted, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={32}
            />
            <ReferenceLine y={0} stroke={theme.colors.hairlineOnDark} />
            <Tooltip
              contentStyle={{
                background: theme.colors.surfaceCardDark,
                border: `1px solid ${theme.colors.hairlineOnDark}`,
                color: theme.colors.body,
              }}
            />
            <Line
              type="monotone"
              dataKey="ic"
              stroke={theme.colors.primary}
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Quantile decile returns bar chart */}
      <div className="mt-md">
        <div className="text-caption text-muted pb-xs">Quantile returns (deciles)</div>
        <div data-testid="factor-quantile-bars" className="flex h-[80px] items-stretch gap-1">
          {factor.quantile_returns.map((v, i) => (
            <QuantileBar key={i} value={v} maxAbs={maxAbs} />
          ))}
        </div>
      </div>
    </Card>
  );
}
