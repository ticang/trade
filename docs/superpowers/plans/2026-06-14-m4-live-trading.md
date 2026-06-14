# M4 实盘灰度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M2 模拟盘闭环通过后，交付只覆盖沪深主板股票的 M4 影子模式到小资金实盘灰度路径。

**Architecture:** M4 不重写策略/风控/执行接口，复用 M1/M1.5/M2 的 FactorRegistry、StrategyRunner、RiskEngine、Broker、OrderBook 与 Repository。新增 live gate、shadow recorder、live audit、kill switch、slippage calibration 与 rollout report，确保实盘路径可停机、可回滚、可复盘。

**Tech Stack:** Python 3.11+ · asyncio · SQLite · DuckDB · xtquant/QMT Windows runtime · Next.js/TanStack Query UI（只读监控优先）

---

## Preconditions

- P0 前后端只读 API bridge 已完成，`/monitor`、`/trade` 能展示后端真实状态。
- M-1b/M2 已完成：QMT live 探测可用，模拟盘连续 20 交易日闭环通过，多账户对账差异 < 0.1%。
- 交易规则、费用、日历、主板 universe 均为 verified；`provisional` 规则继续阻断实盘新开仓。
- 当前交易范围只允许沪深主板股票；科创/创业/北交/ETF/可转债/B 股不得进入 M4。

## Task 1: Live Gate

**Files:**
- Create: `quant/live/gate.py`
- Test: `tests/quant/test_live_gate.py`

- [ ] **Step 1: Write failing tests**
  - `LiveGate.can_open_position` 在规则 `source_confidence != "verified"` 时拒绝。
  - `LiveGate.can_open_position` 在 symbol 非沪深主板时拒绝。
  - `LiveGate.can_open_position` 在 account 未启用 live 时拒绝。
  - `LiveGate.can_open_position` 在 strategy 状态不是 `approved`/`monitoring` 时拒绝。

- [ ] **Step 2: Implement minimal live gate**
  - 返回结构包含 `allowed: bool`、`reason: str`、`snapshot_id: str | None`。
  - 只做门禁判断，不下单、不读 UI、不绕过 Broker。

- [ ] **Step 3: Verify**
  - Run: `.venv/bin/pytest tests/quant/test_live_gate.py -v`
  - Expected: all tests pass.

## Task 2: Shadow Mode Recorder

**Files:**
- Create: `quant/live/shadow.py`
- Test: `tests/quant/test_live_shadow.py`

- [ ] **Step 1: Write failing tests**
  - 实盘行情触发策略建议单，但 `ShadowRunner` 不调用真实 `Broker.place`。
  - 每条建议单记录 symbol、side、qty、price、strategy_id、account_id、risk_verdict、snapshot_id、created_at。
  - 风控拒绝时仍记录 rejected advice，方便复盘。

- [ ] **Step 2: Implement shadow runner**
  - 复用 M2 的行情事件、StrategyRunner 与 RiskEngine。
  - 输出 shadow advice 到 SQLite repository 或现有审计表；没有表时先加最小 schema migration。

- [ ] **Step 3: Verify**
  - Run: `.venv/bin/pytest tests/quant/test_live_shadow.py -v`
  - Expected: Broker mock 未收到 `place` 调用，shadow advice 已落库。

## Task 3: Small-Capital Live Rollout

**Files:**
- Create: `quant/live/rollout.py`
- Test: `tests/quant/test_live_rollout.py`

- [ ] **Step 1: Write failing tests**
  - 小资金实盘只允许白名单策略与白名单账户。
  - 单票市值、行业暴露、日亏损、最大回撤超过配置阈值时拒绝新开仓。
  - 未成交委托数量超过阈值时拒绝继续下单。

- [ ] **Step 2: Implement rollout policy**
  - 配置字段：`max_single_symbol_weight`、`max_industry_weight`、`max_daily_loss`、`max_drawdown`、`max_open_orders`。
  - 策略从 shadow 达标后进入 small-live；失败退回 shadow。

- [ ] **Step 3: Verify**
  - Run: `.venv/bin/pytest tests/quant/test_live_rollout.py -v`
  - Expected: boundary cases pass and rejection reasons are stable strings.

## Task 4: Kill Switch And Rollback

**Files:**
- Create: `quant/live/kill_switch.py`
- Test: `tests/quant/test_live_kill_switch.py`

- [ ] **Step 1: Write failing tests**
  - `KillSwitch.activate(mode="no_open")` 后禁止新开仓，允许平仓。
  - `KillSwitch.activate(mode="cancel_all")` 触发撤未成交委托。
  - `KillSwitch.activate(mode="offline")` 后 strategy 状态转 degraded/offline。

- [ ] **Step 2: Implement kill switch**
  - 所有动作写审计日志，包含 operator、reason、ts、previous_mode、new_mode。
  - 不直接删除订单或持仓，只通过 Broker/OrderBook 的公开接口发指令。

- [ ] **Step 3: Verify**
  - Run: `.venv/bin/pytest tests/quant/test_live_kill_switch.py -v`
  - Expected: state transitions and audit rows match tests.

## Task 5: Live Replay And Slippage Calibration

**Files:**
- Create: `quant/live/calibration.py`
- Test: `tests/quant/test_live_calibration.py`

- [ ] **Step 1: Write failing tests**
  - 用实盘 tick/成交按相同 `snapshot_id` 重放，输出成交价偏差、成交概率偏差、滑点偏差。
  - 当 `snapshot_id` 不一致时拒绝比较。
  - 生成 `bar_level_simulated` 与 live execution 的差异报告。

- [ ] **Step 2: Implement calibration report**
  - 输入：live fills、shadow advice、tick bars、backtest fills、snapshot_id。
  - 输出：`avg_slippage_bps`、`p95_slippage_bps`、`fill_rate_gap`、`calibration_band_passed`。

- [ ] **Step 3: Verify**
  - Run: `.venv/bin/pytest tests/quant/test_live_calibration.py -v`
  - Expected: mismatched snapshot fails; matched synthetic sample produces deterministic metrics.

## Task 6: M4 Acceptance Report

**Files:**
- Create: `docs/review/2026-06-14-m4-live-trading-report.md`
- Modify: `tasks/todo.md`
- Modify: `tasks/HANDOFF.md`

- [ ] **Step 1: Run verification**
  - Run: `.venv/bin/pytest tests/quant -m "not network" -q`
  - Run frontend checks only if M4 UI/API surfaces changed: `cd web && npm test -- --run && npm run build`

- [ ] **Step 2: Record M4 outcome**
  - Report 20 trading-day live/shadow result: account count, traded symbols, reconciliation diff, max drawdown, slippage deviation, kill-switch drills.
  - If any threshold fails, mark M4 as failed and keep system in shadow mode.

- [ ] **Step 3: Update handoff**
  - Add M4 status, exact verification commands, and remaining live-only risks to `tasks/HANDOFF.md`.

## Acceptance Criteria

- [ ] Shadow mode runs on real QMT market data without placing live orders.
- [ ] Small-capital live mode only opens positions when live gate, rollout policy, and verified rules all pass.
- [ ] Kill switch can stop new opens, cancel open orders, and move strategies offline with audit rows.
- [ ] Live replay compares backtest/simulation/live using the same `snapshot_id`.
- [ ] Continuous 20 trading-day live acceptance passes: reconciliation diff < 0.1%, max drawdown < configured threshold, slippage deviation < calibration band.
- [ ] Failure of any acceptance threshold automatically returns the strategy to shadow mode.

## Self-Review

1. **Spec coverage:** Covers design §4.6 execution, §4.7.5 live-backtest consistency, §4.10 observability/kill switch, §11 M4 acceptance.
2. **Scope control:** Does not expand beyond沪深主板股票; does not add real POST trading API before live gate and kill switch exist.
3. **External dependency:** True live verification requires Windows + QMT logged-in runtime; macOS can only run mock/lazy-import tests.
