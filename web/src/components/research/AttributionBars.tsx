"use client";
import { BacktestResult } from "@/types/research";

interface Props {
  attribution: BacktestResult["attribution"];
}

// Horizontal contribution bars per factor. Width is proportional to |contribution|
// relative to the largest magnitude; positive trading-up, negative trading-down.
export function AttributionBars({ attribution }: Props) {
  const sorted = [...attribution].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
  );
  const maxAbs = Math.max(...sorted.map((a) => Math.abs(a.contribution)), 1e-9);

  return (
    <div className="flex flex-col gap-xs">
      {sorted.map(({ factor, contribution }) => {
        const positive = contribution >= 0;
        const widthPct = (Math.abs(contribution) / maxAbs) * 100;
        return (
          <div key={factor} className="flex items-center gap-md">
            <span className="w-40 shrink-0 truncate text-caption text-muted" title={factor}>
              {factor}
            </span>
            <div className="h-[10px] flex-1 overflow-hidden rounded-sm bg-hairline-on-dark/30">
              <div
                data-testid="attribution-bar"
                style={{ width: `${Math.max(widthPct, 2)}%` }}
                className={`h-full rounded-sm ${positive ? "bg-trading-up" : "bg-trading-down"}`}
              />
            </div>
            <span
              className={`w-16 shrink-0 text-right font-number text-number-sm ${
                positive ? "text-trading-up" : "text-trading-down"
              }`}
            >
              {contribution > 0 ? "+" : ""}
              {(contribution * 100).toFixed(2)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
