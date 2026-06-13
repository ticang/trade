import { MarketRow } from "@/types/domain";

export function mockMarkets(): MarketRow[] {
  return [
    { symbol: "000001", name: "平安银行", last: 11.34, change: 0.89, volume: 234_000_000 },
    { symbol: "600519", name: "贵州茅台", last: 1685.5, change: -1.23, volume: 1_200_000_000 },
    { symbol: "300750", name: "宁德时代", last: 182.7, change: 2.45, volume: 890_000_000 },
    { symbol: "002594", name: "比亚迪", last: 245.6, change: -0.56, volume: 567_000_000 },
    { symbol: "688981", name: "中芯国际", last: 48.92, change: 1.78, volume: 445_000_000 },
  ];
}
