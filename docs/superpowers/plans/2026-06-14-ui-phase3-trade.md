# UI 第 3 期：交易终端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking.

**Goal:** 复用 Phase 1/2 设计系统，交付 `/trade` 交易终端：行情 K 线（复用 KlineChart）+ 下单面板（买/卖，trading-up/down 按钮）+ 账户/持仓快照 + 委托/成交列表，mock 数据驱动、币安风格。

**Architecture:** 复用 Phase 1 KlineChart + Phase 2 PositionsTable/StatCard + DESIGN.md tokens。新增交易领域类型（Order/Fill/AccountSnapshot）+ mock + hooks；新增 OrderForm（买/卖切换 + 价格/数量输入 + 预览 + 提交）、OrdersList（委托状态）、FillsList（成交）；组装 `/trade`。

**Tech Stack:** Next.js 14 · TS · Tailwind · TanStack Query（无新依赖）

**关联：** DESIGN.md · v0.5 §4.6（执行层/订单状态机）、§4.5（风控 T+N/涨跌停过滤）、§4.4.1（Signal/on_fill）

**前置：** UI Phase 1/2 完成（`feat/ui-phase1`）。本 Phase 继续此分支。下单交互用 mock（不接真实 broker；实盘在 M2/M4）。

---

## File Structure

```
web/src/
├── types/trade.ts                      # Create: Order/Fill/AccountSnapshot/OrderSide/OrderStatus
├── lib/mock/{orders,fills,account}.ts  # Create
├── hooks/use{Orders,Fills,Account}.ts  # Create
├── components/trade/
│   ├── OrderForm.tsx                   # Create: 买/卖切换 + 价格/数量输入 + 预览 + 提交
│   ├── OrdersList.tsx                  # Create: 委托列表（状态色）
│   ├── FillsList.tsx                   # Create: 成交列表
│   └── TradePanel.tsx                  # Create: K线 + OrderForm 组合
└── app/trade/page.tsx                  # Create
```

---

## Task 1: 交易领域类型 + mock + hooks

**Files:** `types/trade.ts`, `lib/mock/{orders,fills,account}.ts`, `hooks/use{Orders,Fills,Account}.ts`

- [ ] **Step 1: 类型** `types/trade.ts`:
```ts
export type OrderSide = "buy" | "sell";
export type OrderStatus = "pending" | "submitted" | "partial_filled" | "filled" | "cancelled" | "rejected";
export interface Order {
  order_id: string; account_id: string; symbol: string; side: OrderSide;
  price: number; qty: number; filled_qty: number; status: OrderStatus; ts: number;
}
export interface Fill { fill_id: string; order_id: string; symbol: string; side: OrderSide; price: number; qty: number; ts: number; }
export interface AccountSnapshot { account_id: string; cash: number; market_value: number; total: number; available: number; }
```
- [ ] **Step 2: mock**（确定性；orders 含多状态样本，fills 3-4 条，account 2 个账户）
- [ ] **Step 3: hooks**（useOrders/useFills/useAccount，TanStack Query, staleTime Infinity，参照 Phase 1/2 模式）
- [ ] **Step 4:** `npx next build` + `npx vitest run` 无回归 + commit `add trade domain types, mock data, and hooks`

---

## Task 2: OrderForm 组件

**Files:** `components/trade/OrderForm.tsx`, `tests/trade/OrderForm.test.tsx`

- [ ] **Step 1: 失败测试** — 渲染 OrderForm；默认买侧（trading-up 按钮高亮）；切换卖侧（trading-down 高亮）；输入价格+数量后显示预览金额；提交触发 onSubmit 回调带 {side, price, qty}。
- [ ] **Step 2: 实现** — 买/卖 tab（trading-up/down 色，DESIGN.md button-trading-up/down）+ 价格输入（text-input）+ 数量输入 + 快捷比例按钮（25/50/75/100%，基于 available）+ 预览（金额 = price×qty，number 字体）+ 提交按钮（买=trading-up/卖=trading-down）。受控组件（useState）。
- [ ] **Step 3:** 测试通过 + build + commit `add OrderForm component with buy/sell and preview`

---

## Task 3: OrdersList + FillsList

**Files:** `components/trade/{OrdersList,FillsList}.tsx`, `tests/trade/OrdersList.test.tsx`

- [ ] **Step 1: 失败测试** — OrdersList 渲染委托行（标的/方向/价格/数量/已成/状态），状态色（filled=trading-up, cancelled/rejected=muted, pending/submitted=info, partial=primary）；FillsList 渲染成交（标的/方向/价格/数量/时间），方向色。
- [ ] **Step 2: 实现** — 复用 PriceCell 风格；状态/方向 Record 色映射；OrdersList 按 ts 倒序。
- [ ] **Step 3:** 测试通过 + build + commit `add OrdersList and FillsList components`

---

## Task 4: TradePanel + /trade 页面组装

**Files:** `components/trade/TradePanel.tsx`, `app/trade/page.tsx`

- [ ] **Step 1: TradePanel** — grid：左侧 KlineChart（复用 Phase 1，传 mockKline）+ 右侧 OrderForm。上方账户快照（StatCard：总资产/可用/持仓市值）。
- [ ] **Step 2: /trade page** — 组装 TradePanel + PositionsTable（复用 Phase 2，简版或全部）+ grid(OrdersList | FillsList)。on_submit 暂存到本地 state（mock，不接 broker）+ 显示 toast/提示"模拟下单"。
- [ ] **Step 3:** build + vitest 无回归 + `npx next dev` curl /trade 200（渲染标的/买/卖/委托/成交）+ commit `add trade terminal page`

---

## Task 5: 整体验证 + review 修复

- [ ] **Step 1:** `npx next build` + `npx vitest run`（Phase 1+2+3 全测试）+ curl /trade + /replay + /monitor 回归
- [ ] **Step 2:** 整体 code review（spec + quality），修复 follow-ups
- [ ] **Step 3:** commit 修复

---

## Self-Review

1. **Spec 覆盖**：行情K线/下单/账户/委托/成交 → Task 1-4 ✓
2. **复用**：KlineChart/PositionsTable/StatCard/PriceCell/Button 复用 ✓
3. **DESIGN.md**：trading-up/down 买卖按钮、surface-card-dark、number 字体、涨跌停/T+N 提示（mock 阶段标注"模拟"）✓
4. **mock**：不接真实 broker；onSubmit 本地 state + "模拟下单"提示 ✓
5. **已知**：真实下单/风控在 M2/M4；A 股 T+1/涨跌停/最小单位在 OrderForm 提示但不强制（mock）
