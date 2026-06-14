# M1 因子引擎 + 回测引擎 验证报告

> 日期：2026-06-14　分支：`feat/m1-factor-backtest`
> 对照：设计 v0.5 §4.2（因子）、§4.5（风控）、§4.7（回测）、§4.2.3（因子评价）、§4.7.4（归因）、§11 M1
> 范围：M1 五阶段（A 因子引擎核心 / B 因子评价 / C 回测引擎 / D 基础风控 / E 归因+§11 验收）

---

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **216 passed, 1 xfailed, 4 deselected** |
| M1 验收（test_m1_acceptance） | 6/6 绿，确定性（3 次重跑一致），未发现组件 bug |

---

## 2. §11 M1 验收 6 条（E2 逐条）

| # | 验收条 | 实现 | 证据 |
|---|---|---|---|
| 1 | 规则 fixture 100% | M0.5 种子 10 条规则经 load_rules 加载，SimBroker 撮合尊重（科创 min_buy 200 拒 100 单） | test_m1_rule_fixtures_load_and_apply |
| 2 | look-ahead 0 报警 | FactorContext.point 命中未来行抛 LookAheadError；latest 过滤未来；BacktestEngine 含/不含未来行结果一致 | test_m1_no_lookahead_leak |
| 3 | 已知历史事件回放 | 一字板涨停买单 limit_up_sealed；T+1 无持仓卖 no_position_tplusn | test_m1_known_events_replay |
| 4 | 同 snapshot 二次运行一致 | 同 snapshot_id 跑两次 equity_curve assert_series_equal，fills 逐字段等 | test_m1_reproducibility |
| 5 | 连续 3 年无异常 | 750 交易日合成 panel，动量 top-2 策略跑通，权益无 NaN | test_m1_multi_year_run |
| 6 | 基准绩效 sanity | 单调上涨市，等权买入持有终值 ≥ buy-and-hold×0.9（留摩擦） | test_m1_benchmark_sanity |

---

## 3. 组件 vs 设计

### §4.2 因子引擎（Phase A+B）
- ✅ Factor Protocol + FactorContext（**PIT 强制**，因子禁直接读库，防 look-ahead）
- ✅ FactorRegistry.compute_panel（装配 ctx，PIT 透传）
- ✅ 基础因子（动量/反转/波动率，向量化 numpy）
- ✅ snapshot 可复现（确定性 id + checksum，冻结 as_of）
- ✅ 因子评价：rank IC（**行业+log 市值中性化残差**）、IR（**Newey-West**）、10 分层（qcut+兜底）、新颖性（双查）、衰减

### §4.7 回测引擎（Phase C）
- ✅ FrictionModel（佣金/印花税仅卖/过户费/滑点，provisional 标注）
- ✅ SimBroker（事件驱动撮合：限价/市价/缺口开盘、**一字板封死不成交**、量比、**T+N**、tick/lot 合法性，bar_level_simulated）
- ✅ BacktestEngine（事件循环：因子→策略→撮合→mark-to-market，PIT，snapshot 绑定）

### §4.5 风控基础层（Phase D）
- ✅ RiskEngine.check（tick/lot 合法性、停牌/ST/退市过滤、涨停封板、单笔上限、**仓位模拟成交后**单票/总上限、**止损止盈持仓级**、多违收集）

### §4.7.4 绩效归因（Phase E1）
- ✅ regression_attribution（正交化回归，避免共线 Brinson 病态；coef 还原、贡献和≈超额）
- ✅ shapley_attribution（≤3 因子精确 Shapley，>3 降级占位）

---

## 4. 设计原则落实

- **接口先行**：Factor/BacktestStrategy/Broker(SimBroker)/RiskEngine 均为 Protocol/抽象
- **PIT 强制**：FactorContext 行级断言 available_at<=decision_time；look-ahead 0 泄漏（E2-2）
- **可复现**：snapshot_id 冻结 as_of，同 snapshot 二次运行一致（E2-4）
- **回填段打标**：BacktestResult.backtest_on_inferred_pit 字段预留（数据层接入时填）
- **A股规则**：T+N/涨跌停/一字板/tick/lot 全从 TradingRuleProvider 取

---

## 5. 已知延后（按设计，非本次范围）

| 项 | 归属 |
|---|---|
| Strategy 完整引擎（多策略调度/组合优化整数化/生命周期/再平衡） | M1.5 |
| ProcessPool offload / numba 热点优化 | 性能，M2+ |
| DSL 算子 + 单 agent 因子挖掘 | M3 |
| 实盘-回测一致性校验（snapshot 重放） | M4 实盘后 |
| 完整 Shapley（>3 因子）/ Barra CNE6 全风格 | M1.5/M2 |
| 扣费年化/换手（decile_returns）完整口径 | 回测集成时补 |

---

## 6. 结论

**M1 因子引擎 + 回测引擎全部实现并通过 §11 M1 验收 6 条**（216 测试绿，确定性，无组件 bug）。系统核心分析能力就位：因子声明/PIT 计算/中性化评价 + 事件驱动回测/A 股规则撮合/摩擦/基础风控/归因 + snapshot 可复现。可进入 M1.5（策略引擎 + 组合优化）。
