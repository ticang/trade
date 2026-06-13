import { clsx } from "clsx";

interface PriceCellProps {
  value: number;
  direction: "up" | "down" | "flat";
  format?: (v: number) => string;
}

const ARROW = { up: "▲", down: "▼", flat: "—" };
const COLOR = { up: "text-trading-up", down: "text-trading-down", flat: "text-muted" };

export function PriceCell({ value, direction, format }: PriceCellProps) {
  const text = format ? format(value) : String(value);
  return (
    <span className="font-number text-number-md inline-flex items-center gap-1">
      <span className="text-[10px]">{ARROW[direction]}</span>
      <span className={clsx(COLOR[direction])}>{text}</span>
    </span>
  );
}
