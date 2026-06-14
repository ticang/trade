# M5a 情景模拟与复盘引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking. 实现与审查分离。**跨多上下文窗口；每任务边界更新 memory。**

**Goal:** 交付 §4.8 情景模拟与复盘引擎：① 次日情景生成（GARCH/EGARCH-t 波动 + DCC 动态相关，蒙特卡洛 N 路径 + 校准 + AI 融合 + 过撮合）；② 反事实回放（自身小单扰动，边界声明）；③ 每日复盘报告（信号表现/偏差归因/买卖点评分/事件回放）；④ VaR 95%/99% 回测覆盖。覆盖设计 §4.8 + §11 M5a。

**Architecture:** GARCH-t（arch 库）逐 symbol 波动预测；DCC 动态相关（arch 多元或自实现 cDCC）→ 次日协方差。ScenarioGenerator 蒙特卡洛 N 路径（多变量正态 + t 肥尾），路径过 SimBroker 撮合（涨跌停截断/T+1/集合竞价在评估层生效）。AI 融合 `μ_adj = μ_factor + κ·(p_up_ml − 0.5)`。反事实回放复用 event-sourced bar + M1 SimBroker（仅自身小单边界）。复用 M0/M0.5/M1/M1.5/M3。

**Tech Stack:** Python 3.11+ · `arch`（GARCH）· scipy/numpy · 复用全栈。新依赖：`arch>=6.0`

**关联：** §4.8.1（反事实回放）、§4.8.2（次日情景 GARCH/DCC）、§4.8.3（每日复盘）、§7.4（盘后数据流）、§11 M5a

**前置：** M0-M1.5+M3+M-1b/M2 完成（main）。本计划在 `feat/m5a-scenario-replay`。

**验收标准（设计 §11 M5a）：**
1. 复盘报告自动生成
2. GARCH/DCC 校准通过（参数显著/残差无自相关）
3. VaR 95%/99% 回测覆盖率达阈值（Kupiec POF 检验不拒绝）

---

## File Structure

```
quant/
├── scenario/
│   ├── __init__.py
│   ├── garch.py            # GARCH-t 波动预测（arch 库，per symbol）
│   ├── dcc.py              # DCC 动态相关（cDCC 自实现 或 arch 多元）
│   ├── generator.py        # ScenarioGenerator 蒙特卡洛 N 路径 + 校准 + AI 融合
│   └── path_matcher.py     # 路径过撮合（涨跌停截断/T+1/集合竞价在评估层）
├── replay/
│   ├── __init__.py
│   ├── counterfactual.py   # 反事实回放（自身小单扰动，边界声明）
│   ├── daily_report.py     # 每日复盘报告（信号表现/偏差归因/买卖点评分/事件回放）
│   └── var.py              # VaR 95%/99% + Kupiec 回测覆盖
tests/quant/test_scenario_*.py / test_replay_*.py（扁平）
```

---

## Task 1: GARCH-t 波动预测
**Files:** `quant/scenario/garch.py`, `tests/quant/test_scenario_garch.py`
- [ ] **装 arch**：`.venv/bin/pip install --index-url https://pypi.org/simple arch`，pyproject 加 `arch>=6.0`。
- [ ] `GarchForecaster.fit(returns_series)`：arch.arch_model(dist='t') 拟合；`forecast_next() -> (mu, sigma)`。多 symbol 各拟合。
- [ ] 测试：合成 GARCH 数据拟合参数合理；forecast 返回正 sigma；残差白噪声检查（Ljung-Box）。
- [ ] commit `add garch-t volatility forecaster`

## Task 2: DCC 动态相关
**Files:** `quant/scenario/dcc.py`, `tests/quant/test_scenario_dcc.py`
- [ ] `DCC.fit(returns_df)`：cDCC-GARCH（GARCH 残差 + DCC 相关演化，自实现或 arch 多元）。`forecast_cov_next() -> cov_matrix`。
- [ ] 测试：合成相关数据，DCC 估的相关矩阵正定、对角~1；危机态相关↑。
- [ ] commit `add dcc dynamic correlation`

## Task 3: ScenarioGenerator（蒙特卡洛 N 路径 + AI 融合）
**Files:** `quant/scenario/generator.py`, `tests/quant/test_scenario_generator.py`
- [ ] `ScenarioGenerator.generate(mu, cov, n_paths, horizon=1, df_t=5) -> paths[n_paths, n_symbols]`：多变量 t 分布（肥尾）采样。AI 融合 `mu_adj = mu_factor + κ*(p_up_ml - 0.5)`。校准 N 收敛（1%/5% 分位稳定）。
- [ ] 测试：N 路径形状对；t 肥尾（峰度>正态）；分位随 N 增收敛；AI 融合 μ 调整。
- [ ] commit `add scenario generator with monte carlo and ai fusion`

## Task 4: 路径过撮合
**Files:** `quant/scenario/path_matcher.py`, `tests/quant/test_scenario_path_matcher.py`
- [ ] `match_path(path_returns, prev_close, rule_json)`：路径收益 → 价格 → 涨跌停截断（±limit）→ T+1 → 集合竞价（评估层生效，不塞价格过程）。返回 path 的成交可行价。
- [ ] 测试：收益超涨跌停→截断到限价；T+1 卖约束；集合竞价。
- [ ] commit `add scenario path matcher with a-share rules`

## Task 5: 反事实回放（边界声明）
**Files:** `quant/replay/counterfactual.py`, `tests/quant/test_replay_counterfactual.py`
- [ ] `CounterfactualReplay.replay(history_bars, own_trades, modified_trades)`：event-sourced bar 重放，改写自身小单决策观察持仓/盈亏差异。**边界声明**：仅自身小单扰动保证撮合一致；actor/大单移除需价格冲击模型（降级"相关性叙事"）。复用 M1 SimBroker。
- [ ] 测试：自身小单改写→盈亏差异可算；大单场景降级标注。
- [ ] commit `add counterfactual replay with boundary declaration`

## Task 6: VaR + Kupiec 回测
**Files:** `quant/replay/var.py`, `tests/quant/test_replay_var.py`
- [ ] `var(portfolio_paths, alpha=0.95) -> float`（路径分位 VaR）；`kupiec_pof(exceptions, n, alpha) -> (lr_stat, p_value)`（Kupiec POF 检验，覆盖率达标=不拒绝）。
- [ ] 测试：VaR 分位正确；Kupiec LR 公式对照；达标/不达标判定。
- [ ] commit `add var and kupiec backtest`

## Task 7: 每日复盘报告
**Files:** `quant/replay/daily_report.py`, `tests/quant/test_replay_daily_report.py`
- [ ] `DailyReport.generate(date, signals, fills, factor_panel, scenarios, var)`：信号表现（命中率）、实际 vs 预期偏差归因、买卖点质量评分、事件回放（情绪/资金/龙虎榜）；自动归档（落 audit 或 report 文件）。
- [ ] 测试：报告字段齐；命中率/偏差归因计算；归档落库。
- [ ] commit `add daily replay report`

## Task 8: §11 M5a 集成验收
**Files:** `tests/quant/test_m5a_acceptance.py`
- [ ] ① 复盘报告自动生成 ② GARCH/DCC 校准（参数显著/残差白噪声）③ VaR 95%/99% Kupiec 覆盖达标 ④ 路径过撮合涨跌停截断 ⑤ 反事实回放自身小单边界 ⑥ 蒙特卡洛 N 收敛。
- [ ] commit `add m5a acceptance test`

## Task 9: M5a 验证报告
**Files:** `docs/review/2026-06-14-m5a-verification.md`
- [ ] 比照 §4.8 + §11 M5a 出报告。
- [ ] commit `add m5a verification report`

---

## Self-Review
1. **Spec 覆盖**：次日情景 GARCH/DCC+蒙特卡洛+AI融合（Task 1-4）✓ + 反事实回放边界声明（Task 5）✓ + 每日复盘（Task 7）✓ + VaR Kupiec（Task 6）✓ + §11 验收（Task 8）✓
2. **设计原则**：PIT 安全（方向先验用收盘 PIT 特征）、过撮合在评估层（不塞价格过程）、边界声明（仅自身小单）、校准（EWMA/双窗口/N 收敛）
3. **复用**：M1 SimBroker（撮合/规则）、M3 LLM（AI 融合 p_up_ml）、M0 PIT
4. **YAGNI**：价格冲击模型（Almgren-Chriss）留后续；EGARCH 可选 GARCH 起
5. **新依赖**：arch
6. **跨上下文**：每任务边界更新 memory

## 之后
M5b 主体行为学习 → M6 multi-agent → M4 实盘（Windows）
