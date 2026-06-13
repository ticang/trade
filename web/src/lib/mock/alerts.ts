import { Alert } from "@/types/monitor";

// Deterministic alert feed ordered newest-first.
export function mockAlerts(): Alert[] {
  const now = Date.now();
  return [
    {
      ts: now - 3600_000,
      level: "warn",
      title: "事件驱动策略回撤接近阈值",
      detail: "drawdown -18% vs limit -20%",
    },
    {
      ts: now - 7200_000,
      level: "info",
      title: "动量轮动调仓完成",
      detail: "买入 600519, 卖出 000001",
    },
    {
      ts: now - 86400_000,
      level: "error",
      title: "AkShare 数据源延迟",
      detail: "eastmoney 不可达，切换 baostock",
    },
  ];
}
