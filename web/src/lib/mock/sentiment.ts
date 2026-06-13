import { SentimentPoint } from "@/types/domain";
import { mockKline } from "./kline";

export function mockSentiment(): SentimentPoint[] {
  const bars = mockKline();
  let seed = 7;
  const rnd = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  return bars.map((b) => ({ ts: b.ts, score: (rnd() - 0.5) * 1.6 }));
}
