import { clsx } from "clsx";
import { PriceCell } from "./PriceCell";

export interface MarketRow {
  symbol: string;
  name: string;
  last: number;
  change: number; // percent
  volume: number;
}

interface MarketTableProps {
  rows: MarketRow[];
}

const pctFmt = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const numFmt = (v: number) => v.toFixed(2);

const COLOR = { up: "text-trading-up", down: "text-trading-down", flat: "text-muted" };

export function MarketTable({ rows }: MarketTableProps) {
  return (
    <div className="bg-surface-card-dark rounded-xl p-lg text-on-dark">
      <div className="grid grid-cols-4 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>交易对</span>
        <span className="text-right">最新价</span>
        <span className="text-right">24h 涨跌</span>
        <span className="text-right">24h 成交额</span>
      </div>
      {rows.map((r) => {
        const dir = r.change > 0 ? "up" : r.change < 0 ? "down" : "flat";
        return (
          <div
            key={r.symbol}
            className="grid grid-cols-4 gap-md py-sm border-b border-hairline-ondark last:border-0 items-center"
          >
            <div className="flex items-center gap-xs">
              <div className="w-8 h-8 rounded-full bg-surface-elevated-dark" />
              <div>
                <div className={clsx("font-number text-number-md", COLOR[dir])}>{r.symbol}</div>
                <div className="text-caption text-muted">{r.name}</div>
              </div>
            </div>
            <div className="text-right">
              <PriceCell value={r.last} direction={dir} format={numFmt} />
            </div>
            <div className="text-right">
              <PriceCell value={r.change} direction={dir} format={pctFmt} />
            </div>
            <div className="text-right font-number text-number-md text-muted">
              {Math.round(r.volume).toLocaleString()}
            </div>
          </div>
        );
      })}
    </div>
  );
}
