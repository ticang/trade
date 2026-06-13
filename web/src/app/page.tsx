import { Card } from "@/components/ui/Card";

export default function Home() {
  return (
    <div className="space-y-lg">
      <h1 className="text-display-sm">A 股量化交易系统</h1>
      <div className="grid grid-cols-3 gap-lg">
        <Card>
          <div className="p-lg">
            <div className="text-muted text-body-sm">总资产</div>
            <div className="text-number-display text-primary">¥1,234,567</div>
          </div>
        </Card>
        <Card>
          <div className="p-lg">
            <div className="text-muted text-body-sm">当日盈亏</div>
            <div className="text-number-display text-trading-up">+2.34%</div>
          </div>
        </Card>
        <Card>
          <div className="p-lg">
            <div className="text-muted text-body-sm">运行策略</div>
            <div className="text-number-display text-on-dark">3</div>
          </div>
        </Card>
      </div>
    </div>
  );
}
