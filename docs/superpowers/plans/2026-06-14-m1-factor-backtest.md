# M1 因子引擎 + 回测引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking. 实现与审查分离。**本里程碑大，分 A-E 阶段，跨多个上下文窗口执行；每阶段边界更新 memory。**

**Goal:** 交付系统核心分析能力：因子引擎（声明+PIT强制计算+中性化评价）+ 回测引擎（事件驱动撮合+摩擦+A股规则+PIT）+ 基础风控 + snapshot 可复现，满足设计 §11 M1 验收。

**Architecture:** 接口先行——Factor/Strategy/Broker/RiskEngine 均为 Protocol。因子计算经注入的 `FactorContext` 访问数据（禁直接读库，PIT 强制），CPU offload ProcessPool。回测 SimBroker 事件驱动与实盘 on_bar 同路径，摩擦/规则从 TradingRuleProvider 取。snapshot_id 冻结数据快照保证可复现。

**Tech Stack:** Python 3.11+ · pandas/numpy/scipy(stats) · 复用 M0/M0.5（SqliteStore/DuckdbStore/Repository/PIT/TradingRuleProvider/Calendar/Clock）

**关联：** 设计 v0.5 §4.2（因子）、§4.5（风控基础层）、§4.7（回测）、§4.2.3（因子评价）、§4.7.4（归因）、§11 M1

**前置：** M0+M0.5 完成（main）。本计划在 `feat/m1-factor-backtest`。

**验收标准（设计 §11 M1）：**
1. 规则 fixture 100% 通过（复用 M0.5 golden）
2. **look-ahead 0 报警**（PIT 强制 + 因子经 ctx）
3. 已知历史事件回放符合预期
4. **同 snapshot 二次运行一致**（可复现）
5. 连续 3 年（2020+）无异常
6. 基准绩效 sanity（不劣于同 universe buy-and-hold -X%）

---

## File Structure

```
quant/
├── factor/
│   ├── __init__.py
│   ├── context.py             # FactorContext（PIT 强制，注入 decision_time + data access）
│   ├── registry.py            # FactorRegistry.compute_panel(names,t,universe,snapshot_id)
│   ├── snapshot.py            # factor_snapshot/data_snapshot 冻结与加载（可复现）
│   ├── factors/
│   │   ├── __init__.py
│   │   ├── momentum.py        # 基础因子：动量/反转
│   │   └── volatility.py      # 波动率
│   └── eval.py                # 因子评价：rank IC（行业+log市值中性化残差）/IR(Newey-West)/10分层/新颖性/衰减
├── backtest/
│   ├── __init__.py
│   ├── sim_broker.py          # SimBroker 事件驱动撮合（限价/市价/一字板/量比/集合竞价）
│   ├── friction.py            # 交易摩擦（佣金/印花税/过户费/滑点，从 TradingRuleProvider+config）
│   ├── engine.py              # BacktestEngine（事件循环，on_bar 同路径，PIT，snapshot 绑定）
│   └── attribution.py         # 绩效归因（Shapley 简化版 / 回归归因）
└── risk/
    ├── __init__.py
    └── engine.py              # RiskEngine.check（仓位/T+N/涨跌停停牌ST退市/tick数量/止损止盈）
tests/quant/{factor,backtest,risk}/...
```

---

## Phase A：因子引擎核心

### Task A1: FactorContext + PIT 强制
**Files:** `quant/factor/context.py`, `tests/quant/factor/test_context.py`
- [ ] `FactorContext`：持 `decision_time`、`universe`、`snapshot_id`、`data`（PointInTimeSeries 访问器）。所有数据访问经 ctx，**断言 available_at <= decision_time**（PIT，违抛 LookAheadError）。因子代码禁止直接 import duckdb/sqlite（靠 review + ctx 封装保证）。
- [ ] 测试：ctx 读 available_at<=decision_time 的字段 OK；读 future available_at 抛 LookAheadError。
- [ ] commit `add factor context with pit enforcement`

### Task A2: Factor Protocol + FactorRegistry
**Files:** `quant/factor/registry.py`, `tests/quant/factor/test_registry.py`
- [ ] `Factor` Protocol（name/factor_version/inputs/compute(ctx)->Series）；`FactorRegistry.register/compute_panel(names,t,universe,snapshot_id)->DataFrame`。compute_panel 装配 FactorContext 调各 Factor.compute，列=因子。
- [ ] 测试：注册假因子（返回固定 Series），compute_panel 返回 DataFrame 列齐、PIT 断言生效。
- [ ] commit `add factor protocol and registry`

### Task A3: 基础因子（动量/反转 + 波动率）
**Files:** `quant/factor/factors/{momentum,volatility}.py`, `tests/quant/factor/test_basic_factors.py`
- [ ] `MomentumFactor`（N 日收益率）、`ReversalFactor`（短期反转）、`VolatilityFactor`（N 日波动）。各实现 Factor Protocol，inputs 含 close/available_at，经 ctx PIT 读。向量化 numpy。
- [ ] 测试：用合成 panel 算因子值，对照 pandas 参考实现（rank IC 不在此，值正确即可）。
- [ ] commit `add basic momentum reversal and volatility factors`

### Task A4: snapshot 冻结与可复现
**Files:** `quant/factor/snapshot.py`, `tests/quant/factor/test_snapshot.py`
- [ ] `create_snapshot(store, as_of_cap, note) -> snapshot_id`（写 factor_snapshot + data_snapshot checksum）；`load_snapshot(store, snapshot_id)`。compute_panel 绑 snapshot_id：只能读该 snapshot 冻结的 as_of 集合。
- [ ] 测试：同 snapshot 两次 compute_panel 结果一致（可复现）；不同 snapshot（as_of 不同）结果不同。
- [ ] commit `add factor snapshot for reproducibility`

---

## Phase B：因子评价

### Task B1: rank IC + 中性化残差
**Files:** `quant/factor/eval.py`, `tests/quant/factor/test_eval.py`
- [ ] `rank_ic(factor, forward_returns, industry, mktcap)`：Spearman IC 在**行业 + log(市值) 中性化残差**上算（残差 = 回归去行业dummy+log_mktcap 后的残差）。
- [ ] 测试：合成因子+收益+行业+市值，rank_ic 对照手算残差 Spearman；纯随机因子 IC≈0；强因子 IC 显著。
- [ ] commit `add rank ic with industry and size neutralization`

### Task B2: IR（Newey-West）+ 分层 + 新颖性 + 衰减
**Files:** `quant/factor/eval.py`（扩）, `tests/quant/factor/test_eval.py`
- [ ] `information_ratio(ic_series, lag)`（mean/std，Newey-West 调整 t）；`decile_returns(factor, forward_returns)`（10 分位多空扣费年化）；`novelty(factor_values, factor_returns, known_factor_values)`（Spearman+收益预测相关双查 >0.5-0.7 拒）；`ic_decay(ic_by_horizon)`。
- [ ] 测试各指标对照参考实现。
- [ ] commit `add factor evaluation ir decile novelty decay`

---

## Phase C：回测引擎

### Task C1: 交易摩擦
**Files:** `quant/backtest/friction.py`, `tests/quant/backtest/test_friction.py`
- [ ] `FrictionModel`：佣金（config 比例）、印花税（卖方，从 rules.fees.stamp 取，provisional 标注）、过户费（rules.fees.transfer，provisional）、滑点（成交额/波动率简化建模）。`apply(side, price, qty, rule) -> (fill_price, costs)`。
- [ ] 测试：买入无印花税、卖出有；滑点方向；provisional 费用标注（结果带 warning 不阻断回测）。
- [ ] commit `add backtest friction model`

### Task C2: SimBroker 撮合
**Files:** `quant/backtest/sim_broker.py`, `tests/quant/backtest/test_sim_broker.py`
- [ ] `SimBroker`（Broker Protocol，is_synchronous=True）：`place(order)` 事件驱动撮合。限价按盘口/量比（无 L2 保守概率，标 bar_level_simulated）；市价按次日开盘/bar+滑点；**一字板封死=不成交**；成交不超当日量比例；申报价格/数量合法性（tick/lot 从 rules）；T+N（卖 T+1 股票需有持仓）；收盘集合竞价撮合。规则从 TradingRuleProvider 按当日生效版取。
- [ ] 测试：限价成交/不成交、一字板拒、量比限制、T+N 卖出约束、tick/lot 合法性。
- [ ] commit `add sim broker with a-share matching rules`

### Task C3: BacktestEngine 事件循环
**Files:** `quant/backtest/engine.py`, `tests/quant/backtest/test_engine.py`
- [ ] `BacktestEngine`：事件循环遍历交易日（Calendar）→ on_bar（与实盘同路径）→ FactorRegistry.compute_panel（PIT, snapshot 绑定）→ Strategy.on_bar → RiskEngine.check → SimBroker.place → 成交回写。回填段打标 backtest_on_inferred_pit。
- [ ] 测试：简单策略（如等权买入前 N）跑一段合成数据，持仓/盈亏正确，PIT 断言生效，同 snapshot 二次跑一致。
- [ ] commit `add backtest engine event loop`

---

## Phase D：基础风控

### Task D1: RiskEngine
**Files:** `quant/risk/engine.py`, `tests/quant/risk/test_engine.py`
- [ ] `RiskEngine.check(orders, account_id, positions, rules) -> RiskResult`：单票/总仓位上限、T+N 结算（从 rules.settlement）、涨跌停/停牌/ST/退市过滤、tick/数量合法性、止损/止盈/跟踪止损、单笔金额上限。整数化后合法性最终校验。所有规则从 TradingRuleProvider 读。
- [ ] 测试：超仓位拒、T+1 卖无持仓拒、涨跌停价外拒、tick 不合法拒、止损触发；全过即 RiskResult.passed。
- [ ] commit `add basic risk engine`

---

## Phase E：归因 + §11 集成验收

### Task E1: 绩效归因（Shapley 简化 / 回归）
**Files:** `quant/backtest/attribution.py`, `tests/quant/backtest/test_attribution.py`
- [ ] `Attribution`：因子贡献分解。简化版用正交化回归归因（避免共线 Brinson 病态）；多策略相关因子标 Shapley（M1 简化：回归归因为主，Shapley 占位注释）。基准可配置。
- [ ] 测试：合成因子收益，归因分解各因子贡献之和≈总超额。
- [ ] commit `add performance attribution`

### Task E2: §11 M1 集成验收
**Files:** `tests/quant/backtest/test_m1_acceptance.py`
- [ ] 对应 §11 M1 验收 6 条：
  1. 规则 fixture 100%（复用 M0.5 golden 规则跑回测撮合）
  2. **look-ahead 0 报警**（构造 future-available_at 数据，回测/因子访问应抛 LookAheadError 或 0 泄漏）
  3. 已知历史事件回放（合成一字板/T+N 场景，撮合符合预期）
  4. **同 snapshot 二次运行一致**（同 snapshot_id 跑两次，结果逐字段相等）
  5. 连续 3 年（2020+）合成数据无异常跑通
  6. 基准绩效 sanity（等权策略不劣于 buy-and-hold -X%，合成数据）
- [ ] commit `add m1 acceptance test`

### Task E3: M1 验证报告
**Files:** `docs/review/2026-06-14-m1-verification.md`
- [ ] 比照 §4.2/§4.5/§4.7 + §11 M1，出验证报告（前后端 + 因子/回测/风控/归因 覆盖、测试证据、缺口）。
- [ ] commit `add m1 verification report`

---

## Self-Review

1. **Spec 覆盖**（§11 M1）：因子引擎中性化评价（Phase A+B）✓ + 基础因子（A3）✓ + 回测撮合/摩擦/A股规则/一字板/T+N（Phase C）✓ + 风控基础层（D）✓ + PIT强制（A1+C3，§4.7.6）✓ + snapshot可复现（A4）✓ + 绩效归因Shapley简化（E1）✓ + §11 验收6条（E2）✓
2. **设计原则**：接口先行（Factor/Broker/RiskEngine Protocol）✓、PIT 分级（回填段 backtest_on_inferred_pit）✓、因子经 ctx 禁直接读库（A1，防 look-ahead）✓、snapshot 可复现 ✓、风控基础层 M1 就位（§4.5）✓
3. **复用 M0/M0.5**：SqliteStore/DuckdbStore/Repository/PIT/TradingRuleProvider(golden规则)/Calendar/Clock 全复用
4. **YAGNI**：归因 Shapley 占位、Barra CNE6 简化风格因子、numba 热点优化、ProcessPool offload 均延后（M1 先正确性）；DSL 算子/单 agent 挖掘留 M3
5. **已知延后**：实盘-回测一致性校验（§4.7.5，M4 实盘后）；严肃风控层（M4）；多策略调度/组合优化整数化（M1.5）
6. **跨上下文**：Phase A-E 各为独立可验证单元，每阶段边界更新 memory（current phase + 已完成 tasks），压缩/新会话据 memory+本 plan 续。

---

## M1 之后
M1.5（策略引擎+组合优化+生命周期）→ M-1b（xtquant 通道）→ M2（模拟盘主线）→ M3-M6。
