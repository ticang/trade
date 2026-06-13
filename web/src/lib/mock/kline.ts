import { Bar } from "@/types/domain";

// Deterministic synthetic kline (seeded) so the chart is stable across reloads.
export function mockKline(n: number = 240, startPrice = 4100): Bar[] {
  let price = startPrice;
  const bars: Bar[] = [];
  let seed = 42;
  const rnd = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  const dayStart = new Date("2024-03-15T09:30:00").getTime();
  for (let i = 0; i < n; i++) {
    const open = price;
    const drift = (rnd() - 0.48) * 8;
    const close = Math.max(3800, open + drift);
    const high = Math.max(open, close) + rnd() * 3;
    const low = Math.min(open, close) - rnd() * 3;
    const volume = Math.round(50000 + rnd() * 200000);
    bars.push({ ts: dayStart + i * 60_000, open, high, low, close, volume });
    price = close;
  }
  return bars;
}
