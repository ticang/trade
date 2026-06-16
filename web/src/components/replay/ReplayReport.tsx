"use client";
import { Card } from "@/components/ui/Card";
import { KlineChart } from "@/components/charts/KlineChart";
import { SentimentChart } from "@/components/charts/SentimentChart";
import { useKline } from "@/hooks/useKline";
import { useSentiment } from "@/hooks/useSentiment";
import { mockSignals } from "@/lib/mock/signals";
import { QueryState } from "@/components/ui/QueryState";

export function ReplayReport({ symbol }: { symbol: string }) {
  const kline = useKline(symbol);
  const sentiment = useSentiment(symbol);
  const signals = mockSignals();

  return (
    <div className="space-y-lg">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-title-lg text-on-dark">{symbol} 复盘</h2>
          <div className="text-body-sm text-muted">2024-03-15 全天 · 价格 + 成交量 + 散户情绪</div>
        </div>
      </div>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-sm">价格走势 + 成交量 + 信号标注</div>
          <QueryState label="K 线" isLoading={kline.isLoading} isError={kline.isError} isEmpty={!kline.isLoading && !kline.isError && (kline.data?.length ?? 0) === 0} error={kline.error} />
          {kline.data && <KlineChart bars={kline.data} signals={signals} />}
        </div>
      </Card>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-sm">散户情绪曲线</div>
          <QueryState label="情绪" isLoading={sentiment.isLoading} isError={sentiment.isError} isEmpty={!sentiment.isLoading && !sentiment.isError && (sentiment.data?.length ?? 0) === 0} error={sentiment.error} />
          {sentiment.data && <SentimentChart points={sentiment.data} />}
        </div>
      </Card>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-md">信号清单</div>
          <div className="space-y-sm">
            {signals.map((s) => (
              <div key={s.ts} className="flex justify-between text-body-md border-b border-hairline-ondark pb-sm">
                <span className="text-on-dark">{s.label}</span>
                <span
                  className={
                    s.direction === "buy"
                      ? "text-trading-up"
                      : s.direction === "sell"
                        ? "text-trading-down"
                        : "text-primary"
                  }
                >
                  {s.direction === "buy" ? "买" : s.direction === "sell" ? "卖" : "警示"} @ {s.price.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
