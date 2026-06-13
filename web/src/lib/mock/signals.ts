import { ReplaySignal } from "@/types/domain";
import { mockKline } from "./kline";

export function mockSignals(): ReplaySignal[] {
  const bars = mockKline();
  const pick = (i: number) => bars[Math.min(i, bars.length - 1)];
  const s1 = pick(30),
    s2 = pick(75),
    s3 = pick(120),
    s4 = pick(180);
  return [
    { ts: s1.ts, direction: "buy", label: "CPO 起飞", price: s1.close },
    { ts: s2.ts, direction: "warn", label: "风险清仓", price: s2.close },
    { ts: s3.ts, direction: "buy", label: "跌停抄底", price: s3.close },
    { ts: s4.ts, direction: "sell", label: "尾盘防套", price: s4.close },
  ];
}
