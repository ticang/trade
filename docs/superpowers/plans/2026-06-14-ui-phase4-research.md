# UI 第 4 期：研究回测界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking.

**Goal:** 复用 Phase 1-3 设计系统，交付 `/research` 研究回测界面：因子评价（IC 时序 + 分层条形）+ 回测结果（净值曲线 + 回撤 + 关键指标 + 归因）+ 策略生命周期管理，mock 数据驱动、币安风格。

**Architecture:** 复用 recharts（Phase 1 SentimentChart）+ Phase 2 LifecycleBadge/Card/StatCard。新增研究类型（FactorEval/BacktestResult/StrategyLifecycleEntry）+ mock + hooks；新增 FactorEvalChart、BacktestResultPanel、StrategyLifecycleTable；组装 `/research`。

**Tech Stack:** Next.js 14 · TS · Tailwind · recharts · TanStack Query（无新依赖）

**关联：** DESIGN.md · v0.5 §4.2.3（因子评价 IC/IR/分层/新颖性）、§4.7（回测/绩效归因）、§4.4.4（策略生命周期）

**前置：** UI Phase 1/2/3 完成（`feat/ui-phase1`）。

---

## File Structure

```
web/src/
├── types/research.ts                          # Create: FactorEval/BacktestResult/StrategyLifecycleEntry
├── lib/mock/{factor_eval,backtest,strategy_lifecycle}.ts
├── hooks/use{FactorEval,Backtest,StrategyLifecycle}.ts
├── components/research/
│   ├── FactorEvalChart.tsx                    # IC 时序线 + 分层条形（recharts）
│   ├── BacktestResultPanel.tsx                # 净值曲线 + 回撤 + 指标 StatCards + 归因条
│   ├── StrategyLifecycleTable.tsx             # 复用 LifecycleBadge + 流转按钮（mock）
│   └── AttributionBars.tsx                    # 因子贡献条形
└── app/research/page.tsx
```

---

## Task 1: 研究类型 + mock + hooks

**Files:** `types/research.ts`, `lib/mock/{factor_eval,backtest,strategy_lifecycle}.ts`, `hooks/use{FactorEval,Backtest,StrategyLifecycle}.ts`

- [ ] **Step 1: 类型** `types/research.ts`:
```ts
export interface FactorEval {
  name: string; ic_series: { ts: number; ic: number }[];
  ic: number; ir: number; turnover: number;
  quantile_returns: number[];   // 10 分位多空年化
  novelty_corr: number;         // 与已知因子相关性
}
export interface BacktestPoint { ts: number; equity: number; drawdown: number; benchmark: number; }
export interface BacktestResult {
  strategy: string; series: BacktestPoint[];
  annual_return: number; sharpe: number; max_drawdown: number; win_rate: number; turnover: number;
  attribution: { factor: string; contribution: number }[];
}
export interface StrategyLifecycleEntry { name: string; status: StrategyStatus; oos_ic: number; approved_by: string | null; degraded_reason: string | null; }
```
（StrategyStatus 从 types/monitor 复用）
- [ ] **Step 2: mock**（确定性；factor_eval 2-3 个因子含 IC 时序；backtest 1 个策略净值+回撤序列+归因 4-5 因子；strategy_lifecycle 3-4 条含各状态）
- [ ] **Step 3: hooks**（TanStack Query, staleTime Infinity）
- [ ] **Step 4:** build + vitest 无回归 + commit `add research domain types, mock data, and hooks`

---

## Task 2: FactorEvalChart

**Files:** `components/research/FactorEvalChart.tsx`, `tests/research/FactorEvalChart.test.tsx`

- [ ] **Step 1: 失败测试** — 渲染 FactorEvalChart(mock 因子)；显示因子名/IC/IR/换手/新颖性；IC 时序线渲染（recharts LineChart，引用 data-testid）；分层条形（10 分位）渲染。
- [ ] **Step 2: 实现** — Card：顶部因子元数据（name + IC/IR/turnover/novelty 数字，IC>0 绿）；IC 时序 LineChart（recharts，trading-up/down 参考线 0）；分层 QuantileBarChart（10 柱，单调则首尾色）。
- [ ] **Step 3:** 测试通过 + build + commit `add FactorEvalChart component`

---

## Task 3: BacktestResultPanel + AttributionBars

**Files:** `components/research/{BacktestResultPanel,AttributionBars}.tsx`, `tests/research/BacktestResultPanel.test.tsx`

- [ ] **Step 1: 失败测试** — 渲染 BacktestResultPanel(mock)；显示策略名 + 关键指标（年化/夏普/最大回撤/胜率/换手，回撤红）；净值曲线（AreaChart 或 LineChart，含 benchmark 线）；回撤副图；归因条形（AttributionBars）显示各因子贡献，正绿负红。
- [ ] **Step 2: 实现 BacktestResultPanel** — Card：指标 StatCards 行 + 净值 ComposedChart（equity Area + benchmark Line）+ 回撤 AreaChart（trading-down 色）。
- [ ] **Step 3: 实现 AttributionBars** — 水平条形（因子名 + 贡献条，正 trading-up 负 trading-down）。
- [ ] **Step 4:** 测试通过 + build + commit `add BacktestResultPanel and AttributionBars`

---

## Task 4: StrategyLifecycleTable + /research 页面

**Files:** `components/research/StrategyLifecycleTable.tsx`, `app/research/page.tsx`

- [ ] **Step 1: StrategyLifecycleTable** — 复用 LifecycleBadge；列（策略/badge/OOS IC/审批人/降级原因）；mock 流转按钮（如 paper→approve，本地 state，不接真后端）。
- [ ] **Step 2: /research page** — 组装：h1 "研究回测" + FactorEvalChart(多因子切换 tab) + BacktestResultPanel + StrategyLifecycleTable。client 组件 + hooks。
- [ ] **Step 3:** build + vitest 无回归 + dev curl /research 200 + commit `add research dashboard page`

---

## Task 5: 整体验证 + review 修复

- [ ] **Step 1:** build + vitest（Phase 1-4 全测试）+ curl /research + /replay + /monitor + /trade 回归
- [ ] **Step 2:** 整体 code review（spec + quality），修复 follow-ups
- [ ] **Step 3:** commit 修复

---

## Self-Review

1. **Spec 覆盖**：因子评价(IC/分层)/回测结果(净值/回撤/归因)/策略生命周期 → Task 1-4 ✓
2. **复用**：recharts/Card/StatCard/LifecycleBadge/PriceCell ✓
3. **DESIGN.md**：trading-up/down、primary、surface-card-dark、number 字体 ✓
4. **mock**：确定性；策略流转本地 state（mock，不接真后端）✓
5. **已知**：真实因子评价/回测引擎在后端 M1/M3；UI mock 展示
