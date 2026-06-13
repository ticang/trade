# UI 第 2 期：监控面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development to implement task-by-task. Checkbox (`- [ ]`) tracking.

**Goal:** 复用 Phase 1 设计系统，交付 `/monitor` 监控面板：持仓表（多账户）、盈亏概览、策略状态表（含生命周期 badge）、风控面板、告警列表，全部 mock 数据驱动、币安风格。

**Architecture:** 复用 Phase 1 的 Tailwind theme + 基础组件（Card/Button/PriceCell）+ mock/hooks 模式。新增监控领域类型（Position/Strategy/RiskState/Alert）+ mock + hooks，新增 PositionsTable/StrategyTable/LifecycleBadge/RiskPanel/AlertList 组件，组装 `/monitor` 页面。

**Tech Stack:** Next.js 14 · TypeScript · Tailwind · TanStack Query（同 Phase 1，无新依赖）

**关联：** DESIGN.md（视觉）· v0.5 §4.4.4（策略生命周期）、§4.5（风控分层）、§4.10（可观测性）

**前置：** UI Phase 1 完成（分支 `feat/ui-phase1`）。本 Phase 继续在此分支累积。

---

## File Structure

```
web/src/
├── types/
│   └── monitor.ts            # Create: Position/Strategy/RiskState/Alert 类型
├── lib/mock/
│   ├── positions.ts          # Create
│   ├── strategies.ts         # Create
│   ├── risk.ts               # Create
│   └── alerts.ts             # Create
├── hooks/
│   ├── usePositions.ts       # Create
│   ├── useStrategies.ts      # Create
│   ├── useRisk.ts            # Create
│   └── useAlerts.ts          # Create
├── components/
│   ├── monitor/
│   │   ├── PositionsTable.tsx     # Create
│   │   ├── StrategyTable.tsx      # Create
│   │   ├── LifecycleBadge.tsx     # Create
│   │   ├── RiskPanel.tsx          # Create
│   │   ├── AlertList.tsx          # Create
│   │   └── PnlOverview.tsx        # Create
│   └── ui/
│       └── StatCard.tsx           # Create（盈亏概览卡片，复用 Card）
└── app/monitor/
    └── page.tsx              # Create
```

---

## Task 1: 监控领域类型 + mock + hooks

**Files:** `types/monitor.ts`, `lib/mock/{positions,strategies,risk,alerts}.ts`, `hooks/{usePositions,useStrategies,useRisk,useAlerts}.ts`

- [ ] **Step 1: 类型** `web/src/types/monitor.ts`:
```ts
export interface Position {
  account_id: string; symbol: string; name: string;
  qty: number; avg_cost: number; last: number;
  market_value: number; pnl: number; pnl_pct: number; weight: number;
}
export type StrategyStatus = "draft" | "backtested" | "paper" | "approved" | "live" | "monitoring" | "degraded" | "offline";
export interface Strategy {
  name: string; status: StrategyStatus; account_id: string;
  ic: number; turnover: number; drawdown: number; allocation: number;
}
export interface RiskState {
  total_position_pct: number; max_single_pct: number;
  industry_exposure: { industry: string; pct: number }[];
  drawdown: number; drawdown_limit: number; circuit_breaker: "normal" | "degraded" | "halted";
}
export type AlertLevel = "info" | "warn" | "error";
export interface Alert { ts: number; level: AlertLevel; title: string; detail: string; }
```

- [ ] **Step 2: mock 数据** `web/src/lib/mock/positions.ts` 等（5-8 条记录，确定性）:
```ts
// positions.ts
import { Position } from "@/types/monitor";
export function mockPositions(): Position[] {
  return [
    { account_id: "acct1", symbol: "600519", name: "贵州茅台", qty: 100, avg_cost: 1650, last: 1685.5, market_value: 168550, pnl: 3550, pnl_pct: 2.15, weight: 0.32 },
    { account_id: "acct1", symbol: "300750", name: "宁德时代", qty: 300, avg_cost: 178, last: 182.7, market_value: 54810, pnl: 1410, pnl_pct: 2.64, weight: 0.10 },
    { account_id: "acct1", symbol: "000001", name: "平安银行", qty: 5000, avg_cost: 11.5, last: 11.34, market_value: 56700, pnl: -800, pnl_pct: -1.39, weight: 0.11 },
    { account_id: "acct2", symbol: "002594", name: "比亚迪", qty: 200, avg_cost: 250, last: 245.6, market_value: 49120, pnl: -880, pnl_pct: -1.76, weight: 0.09 },
  ];
}
// strategies.ts — 3 strategies varied statuses
export function mockStrategies() {
  return [
    { name: "动量轮动", status: "live" as const, account_id: "acct1", ic: 0.062, turnover: 0.45, drawdown: -0.08, allocation: 0.5 },
    { name: "情绪反向", status: "paper" as const, account_id: "acct1", ic: 0.038, turnover: 0.62, drawdown: -0.12, allocation: 0.3 },
    { name: "事件驱动", status: "degraded" as const, account_id: "acct2", ic: 0.015, turnover: 0.88, drawdown: -0.18, allocation: 0.2 },
  ];
}
// risk.ts
export function mockRisk() {
  return {
    total_position_pct: 0.62, max_single_pct: 0.32,
    industry_exposure: [
      { industry: "白酒", pct: 0.32 }, { industry: "新能源", pct: 0.19 }, { industry: "银行", pct: 0.11 },
    ],
    drawdown: -0.08, drawdown_limit: -0.15, circuit_breaker: "normal" as const,
  };
}
// alerts.ts
export function mockAlerts() {
  return [
    { ts: Date.now() - 3600_000, level: "warn" as const, title: "事件驱动策略回撤接近阈值", detail: "drawdown -18% vs limit -20%" },
    { ts: Date.now() - 7200_000, level: "info" as const, title: "动量轮动调仓完成", detail: "买入 600519, 卖出 000001" },
    { ts: Date.now() - 86400_000, level: "error" as const, title: "AkShare 数据源延迟", detail: "eastmoney 不可达，切换 baostock" },
  ];
}
```

- [ ] **Step 3: hooks**（4 个，TanStack Query, staleTime Infinity，参照 Phase 1 useKline 模式）

- [ ] **Step 4: build 验证 + commit** `add monitor domain types, mock data, and hooks`

---

## Task 2: PositionsTable 组件

**Files:** `components/monitor/PositionsTable.tsx`, `tests/monitor/PositionsTable.test.tsx`

- [ ] **Step 1: 失败测试** — 渲染表头（账户/标的/数量/成本/现价/市值/盈亏/权重），每行盈亏按方向着色（pnl>0 绿，<0 红），按 account 分组。
- [ ] **Step 2: 实现** — 复用 PriceCell。pnl 列用 `text-trading-up/down`。表头 `text-muted`，行 `border-hairline-ondark`。
- [ ] **Step 3: 测试通过 + commit** `add PositionsTable component`

---

## Task 3: LifecycleBadge + StrategyTable

**Files:** `components/monitor/LifecycleBadge.tsx`, `components/monitor/StrategyTable.tsx`, `tests/monitor/StrategyTable.test.tsx`

- [ ] **Step 1: LifecycleBadge** — 按 StrategyStatus 渲染色标：live=trading-up、paper=primary、degraded=trading-down、offline=muted、其他=info。圆角 sm，caption 字号。
- [ ] **Step 2: 失败测试** — StrategyTable 渲染策略行（名称/badge/IC/换手/回撤/配比），回撤红色，IC 正绿。
- [ ] **Step 3: 实现 StrategyTable** — 用 LifecycleBadge。
- [ ] **Step 4: 测试通过 + commit** `add LifecycleBadge and StrategyTable components`

---

## Task 4: RiskPanel + AlertList

**Files:** `components/monitor/RiskPanel.tsx`, `components/monitor/AlertList.tsx`, `tests/monitor/RiskPanel.test.tsx`

- [ ] **Step 1: RiskPanel** — 卡片显示总仓位%/单票上限%/回撤（vs limit 进度条）/熔断状态（normal 绿/degraded 黄/halted 红）+ 行业暴露条形。
- [ ] **Step 2: AlertList** — 按级别着色（error trading-down / warn primary / info muted），时间倒序。
- [ ] **Step 3: 失败测试** — RiskPanel 渲染熔断状态 + 回撤值；circuit_breaker=normal 时熔断标 trading-up。
- [ ] **Step 4: 实现测试通过 + commit** `add RiskPanel and AlertList components`

---

## Task 5: StatCard + PnlOverview + /monitor 页面

**Files:** `components/ui/StatCard.tsx`, `components/monitor/PnlOverview.tsx`, `app/monitor/page.tsx`

- [ ] **Step 1: StatCard** — 复用 Card，prop: label/value/direction（涨跌色）。通用盈亏概览单元。
- [ ] **Step 2: PnlOverview** — 4 个 StatCard：总资产/当日盈亏/累计盈亏/运行策略数。从 mockPositions 聚合。
- [ ] **Step 3: /monitor page** — 组装 PnlOverview + grid(PositionsTable + RiskPanel) + StrategyTable + AlertList。
- [ ] **Step 4: build + dev 验证（curl /monitor 200 + 关键内容）+ commit** `add monitor dashboard page`

---

## Task 6: 整体验证

- [ ] **Step 1:** `cd web && npx next build` 成功
- [ ] **Step 2:** `cd web && npx vitest run` 全测试通过（Phase 1 + Phase 2）
- [ ] **Step 3:** `npx next dev` → curl /monitor 确认渲染持仓/策略/风控/告警
- [ ] **Step 4:** 若有 lint/type 小问题修复

---

## Self-Review

1. **Spec 覆盖**：持仓表/盈亏/策略状态(含生命周期)/风控/告警 → Task 1-5 ✓
2. **DESIGN.md 保真**：复用 Phase 1 tokens（trading up/down、primary、muted、surface-card-dark、hairline）✓
3. **复用**：Card/Button/PriceCell 复用，无重复造轮子 ✓
4. **mock 确定性 + hooks 抽象**：后续接真 API 改 queryFn ✓
5. **已知**：/trade /research 路由占位（Phase 3/4）；告警无实时推送（mock 静态）
