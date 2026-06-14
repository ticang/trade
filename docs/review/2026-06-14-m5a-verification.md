# M5a 情景模拟与复盘引擎 验证报告

> 日期：2026-06-14　分支：`feat/m5a-scenario-replay`
> 对照：设计 v0.5 §4.8.1（反事实回放）、§4.8.2（次日情景 GARCH/DCC）、§4.8.3（每日复盘）、§7.4、§11 M5a

---

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **512 passed, 1 xfailed, 6 deselected** |
| M5a 验收（test_m5a_acceptance） | 7/7 绿，确定性（seed=2024，3 次重跑一致） |

---

## 2. §11 M5a 验收

| # | 验收条 | 实现 | 证据 |
|---|---|---|---|
| 1 | 复盘报告自动生成 | DailyReport.generate_daily_report 组装+归档（audit_event） | test_m5a_report_auto_generated |
| 2 | GARCH/DCC 校准通过 | GarchForecaster（arch 库 t 分布）+ DCC cDCC；残差 Ljung-Box p>0.05 | test_m5a_garch_dcc_calibrated |
| 3 | VaR 95%/99% 回测覆盖达标 | value_at_risk + kupiec_pof；5%例外率 at 95% → p>0.05 不拒绝 | test_m5a_var_kupiec_coverage |
| 4 | 路径过撮合涨跌停截断 | path_matcher（评估层截断/T+1/集合竞价，不塞价格过程） | test_m5a_path_limit_truncation |
| 5 | 反事实回放边界声明 | CounterfactualReplay（自身小单因果，大单降级"相关性叙事"） | test_m5a_counterfactual_small_order_boundary |
| 6 | 蒙特卡洛 N 收敛 | ScenarioGenerator.quantile_convergence（N=5000 vs 1000 分位稳定） | test_m5a_monte_carlo_convergence |
| — | 端到端管道 | GARCH→DCC→N路径→path_matcher→VaR→DailyReport | test_m5a_end_to_end_pipeline |

---

## 3. 组件 vs 设计

### §4.8.2 次日情景生成
- ✅ GarchForecaster（arch 库 GARCH-t，波动聚集+肥尾，残差白噪声校验）
- ✅ DCC（cDCC 动态相关，危机态相关↑，正定/对角1）
- ✅ ScenarioGenerator（多变量 t 蒙特卡洛 N 路径 + AI 融合 `μ_adj=μ_factor+κ(p_up_ml-0.5)` + N 收敛校准）
- ✅ path_matcher（涨跌停截断/T+1/集合竞价在**评估层**生效）

### §4.8.1 反事实回放
- ✅ CounterfactualReplay（event-sourced bar 重放，复用 M1 SimBroker，**边界声明**：仅自身小单因果，大单降级）

### §4.8.3 每日复盘
- ✅ DailyReport（信号命中率/偏差归因/买卖点评分/事件回放/归档 audit_event）

### VaR 回测
- ✅ value_at_risk + conditional_var（CVaR）+ kupiec_pof（POF 检验，达标=不拒绝）

---

## 4. 设计原则落实

- **过撮合在评估层**（§4.8.2）：价格过程连续，规则在评估时施加（path_matcher）
- **边界声明**（§4.8.1）：仅自身小单保证撮合一致；actor/大单需冲击模型，降级"相关性叙事"
- **校准**（§4.8.2）：GARCH 残差白噪声（Ljung-Box）；蒙特卡洛 N 收敛（分位稳定）
- **PIT 安全**：方向先验用收盘 PIT 特征（设计意图，接入因子时生效）

---

## 5. 已知延后（按设计）

| 项 | 归属 |
|---|---|
| EGARCH 切换 / 跳跃强度估计 | Task 1 GarchForecaster 已支持 vol='Egarch' 传入；跳跃留后续 |
| 价格冲击模型（Almgren-Chriss） | 大单反事实降级，留后续 |
| MLE 估 DCC α/β | 当前固定 α/β 简化，留后续 |
| AI 预测融合完整闭环 | μ_adj 公式已就位，p_up_ml 接 LLM 留 M5b 集成 |
| 真实历史 VaR 回测 | 合成数据验证，M5b 接历史序列 |

---

## 6. 结论

**M5a 情景模拟与复盘引擎全部实现并通过 §11 M5a 验收**（512 测试绿，确定性）。次日情景（GARCH/DCC + 蒙特卡洛 t 路径 + AI 融合 + 评估层过撮合）+ 反事实回放（边界声明）+ 每日复盘报告 + VaR/CVaR/Kupiec 回测就位。可进入 M5b（主体行为学习）或 M6（multi-agent）。
