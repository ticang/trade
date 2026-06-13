"use client";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { AttributionBars } from "@/components/research/AttributionBars";
import { BacktestResult } from "@/types/research";
import { theme } from "@/lib/theme";

interface Props {
  result: BacktestResult;
}

interface MetricDef {
  key: string;
  label: string;
  value: string;
  direction: "up" | "down" | "flat";
  testId: string;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function buildMetrics(r: BacktestResult): MetricDef[] {
  return [
    {
      key: "annual_return",
      label: "年化收益",
      value: pct(r.annual_return),
      direction: r.annual_return >= 0 ? "up" : "down",
      testId: "backtest-metric-annual_return",
    },
    {
      key: "sharpe",
      label: "夏普",
      value: r.sharpe.toFixed(2),
      direction: r.sharpe >= 0 ? "up" : "down",
      testId: "backtest-metric-sharpe",
    },
    {
      key: "max_drawdown",
      label: "最大回撤",
      value: pct(r.max_drawdown),
      // Drawdown is always non-positive; render red.
      direction: "down",
      testId: "backtest-metric-max_drawdown",
    },
    {
      key: "win_rate",
      label: "胜率",
      value: pct(r.win_rate),
      direction: "flat",
      testId: "backtest-metric-win_rate",
    },
    {
      key: "turnover",
      label: "换手",
      value: r.turnover.toFixed(2),
      direction: "flat",
      testId: "backtest-metric-turnover",
    },
  ];
}

const COLOR: Record<MetricDef["direction"], string> = {
  up: "text-trading-up",
  down: "text-trading-down",
  flat: "text-body",
};

const tooltipStyle = {
  background: theme.colors.surfaceCardDark,
  border: `1px solid ${theme.colors.hairlineOnDark}`,
  color: theme.colors.body,
};

export function BacktestResultPanel({ result }: Props) {
  const metrics = buildMetrics(result);

  return (
    <Card variant="surface-dark" className="p-lg">
      <h3 className="text-title-md text-body">{result.strategy}</h3>

      {/* Key metrics row */}
      <div className="mt-md grid grid-cols-2 gap-md sm:grid-cols-3 lg:grid-cols-5">
        {metrics.map((m) => (
          <div key={m.key} className="flex flex-col">
            <span className="text-caption text-muted">{m.label}</span>
            <span
              data-testid={m.testId}
              className={`font-number text-number-md pt-xs ${COLOR[m.direction]}`}
            >
              {m.value}
            </span>
          </div>
        ))}
      </div>

      {/* Equity curve: Area (strategy) + Line (benchmark) */}
      <div data-testid="backtest-equity-chart" className="mt-lg h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={result.series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={theme.colors.primary} stopOpacity={0.25} />
                <stop offset="100%" stopColor={theme.colors.primary} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <XAxis dataKey="ts" tick={false} axisLine={{ stroke: theme.colors.hairlineOnDark }} />
            <YAxis
              tick={{ fill: theme.colors.muted, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={40}
              domain={["auto", "auto"]}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Area
              type="monotone"
              dataKey="equity"
              stroke={theme.colors.primary}
              strokeWidth={1.5}
              fill="url(#equity-fill)"
            />
            <Line
              type="monotone"
              dataKey="benchmark"
              stroke={theme.colors.muted}
              strokeWidth={1}
              strokeDasharray="3 3"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Drawdown chart */}
      <div data-testid="backtest-drawdown-chart" className="mt-md h-[120px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={result.series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="drawdown-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={theme.colors.tradingDown} stopOpacity={0.05} />
                <stop offset="100%" stopColor={theme.colors.tradingDown} stopOpacity={0.3} />
              </linearGradient>
            </defs>
            <XAxis dataKey="ts" tick={false} axisLine={{ stroke: theme.colors.hairlineOnDark }} />
            <YAxis
              tick={{ fill: theme.colors.muted, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={40}
              domain={[result.max_drawdown, 0]}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke={theme.colors.tradingDown}
              strokeWidth={1}
              fill="url(#drawdown-fill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Attribution */}
      <div className="mt-lg">
        <div className="text-caption text-muted pb-xs">归因 (Attribution)</div>
        <AttributionBars attribution={result.attribution} />
      </div>
    </Card>
  );
}
