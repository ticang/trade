# M5b 主体行为学习层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking. 实现与审查分离。**跨多上下文窗口；每任务边界更新 memory。LLM 读 .env（DashScope）。**

**Goal:** 交付 §4.9 主体行为学习：Actor 抽象 + 样本库（龙虎榜/北向/自身，标签=实现 PnL）+ 三路并行学习（统计画像/AI 归纳/ML 模仿，按 actor 切 OOS）+ **标准门禁**（复用 M3 BH-FDR+新颖性+经济，删"两路共识"）+ 自身画像降级（审计+规则提醒）。覆盖设计 §4.9 + §11 M5b。

**Architecture:** Actor/ActorTrade 数据模型；样本库按 actor kind 聚合（带偏差声明：游资仅上榜股子集、自身小样本降级）。三路并行：统计画像（胜率/盈亏比/持仓周期/板块/买卖点）、AI 归纳（LLM 读样本归纳高胜率条件，喂 M3 DSL+已知因子查重）、ML 模仿（标签=actor 实现 PnL 非"是否盈利"防前视，特征 PIT，按 actor 切 OOS）。入库走标准门禁（复用 M3 Tester，方法一致性作鲁棒性证据非入库依据）。自身画像降级为审计+规则化提醒（追高/割肉/持仓过久）。

**Tech Stack:** Python 3.11+ · numpy/pandas/scipy · 复用 M3（DSL/LLMClient/Tester/ExperimentTracker）。无新依赖

**关联：** §4.9.1（Actor 抽象）、§4.9.2（数据源偏差）、§4.9.3（三路学习）、§4.9.4（标准门禁）、§4.9.5（自身降级）、§11 M5b

**前置：** M0-M1.5+M3+M-1b/M2+M5a 完成（main）。本计划在 `feat/m5b-actor-learning`。

**验收标准（设计 §11 M5b）：**
1. 行为因子经标准门禁（BH-FDR+新颖性+经济显著+人审）入库——**M3 同一门禁**
2. 三路学习按 actor 切 OOS
3. 自身画像降级（小样本→审计+规则提醒）

---

## File Structure

```
quant/
├── actor/
│   ├── __init__.py
│   ├── model.py              # Actor/ActorTrade/ActorKind
│   ├── sample_lib.py         # ActorSampleLibrary（按 kind 聚合 + 偏差声明）
│   ├── stat_profile.py       # 路径1：统计画像（胜率/盈亏比/持仓周期/板块/买卖点）
│   ├── ai_induct.py          # 路径2：AI 归纳（LLM 读样本→高胜率条件，DSL+已知因子查重）
│   ├── ml_imitate.py         # 路径3：ML 模仿（标签=PnL，PIT 特征，按 actor 切 OOS）
│   └── self_audit.py         # 自身画像降级（审计+规则提醒：追高/割肉/持仓过久）
tests/quant/test_actor_*.py（扁平）
```

---

## Task 1: Actor 抽象 + 样本库（偏差声明）
**Files:** `quant/actor/{model,sample_lib}.py`, `tests/quant/test_actor_model.py`
- [ ] ActorKind（SELF/HOT_MONEY/NORTHBOUND/INSTITUTION）、Actor(id/kind/trades)、ActorTrade(symbol/time/side/price/volume/realized_pnl/context)。SampleLibrary 按 kind 聚合 + 偏差声明（游资仅上榜股子集、自身小样本降级标注）。
- [ ] 测试：Actor/ActorTrade 字段；SampleLibrary 按 kind 过滤；偏差声明字段。
- [ ] commit `add actor abstraction and sample library`

## Task 2: 统计画像（路径1）
**Files:** `quant/actor/stat_profile.py`, `tests/quant/test_actor_stat_profile.py`
- [ ] stat_profile(trades) → 胜率/盈亏比/平均持仓周期/板块偏好/买卖点特征（买入后 N 日收益分布）。可解释画像。
- [ ] 测试：合成 trades 算指标对照手算。
- [ ] commit `add statistical actor profile`

## Task 3: AI 归纳（路径2，LLM）
**Files:** `quant/actor/ai_induct.py`, `tests/quant/test_actor_ai_induct.py`
- [ ] AIInduct.induct(actor, trades, known_factors) → LLM 读样本归纳高胜率条件 → 候选 DSL 因子/规则；M3 Sandbox.validate + 已知因子查重（复用 M3 novelty_check）。mock LLM 测 + network 标记。
- [ ] 测试：mock LLM 返回 DSL，归纳产出候选；未注册算子拒；network 真实 LLM 跑。
- [ ] commit `add ai actor induction`

## Task 4: ML 模仿（路径3，按 actor 切 OOS）
**Files:** `quant/actor/ml_imitate.py`, `tests/quant/test_actor_ml_imitate.py`
- [ ] MLImitate.fit(trades_by_actor, features) → 标签=realized_pnl（非"是否盈利"防前视）；特征 PIT 约束；**按 actor 切 OOS**（某 actor 训练则该 actor 全期 OOS，Leave-One-Actor-Out）。简化：线性回归/scipy。
- [ ] 测试：合成 trades，LOAO 切分；标签=PnL；PIT 特征。
- [ ] commit `add ml actor imitation with leave one actor out`

## Task 5: 标准门禁（复用 M3，删两路共识）
**Files:** `quant/actor/gate.py`, `tests/quant/test_actor_gate.py`
- [ ] ActorGate.test(candidate_factor, ...) → 复用 M3 Tester（BH-FDR+新颖性+经济）。**删"两路共识即入库"**（§4.9.4：同源非独立，方法一致性作鲁棒性证据非入库依据）。返回 GateResult(passed, method_consistency, reasons)。
- [ ] 测试：候选经标准门禁；三路一致性字段（不门控）；pass/fail。
- [ ] commit `add actor standard gate reusing m3 tester`

## Task 6: 自身画像降级（审计+规则提醒）
**Files:** `quant/actor/self_audit.py`, `tests/quant/test_actor_self_audit.py`
- [ ] SelfAudit.audit(self_trades) → 交易行为审计 + 规则化提醒（追高买/割肉卖/持仓过久），非建模。返回提醒列表。
- [ ] 测试：追高/割肉/持仓过久检测。
- [ ] commit `add self trade audit with rule reminders`

## Task 7: §11 M5b 集成验收
**Files:** `tests/quant/test_m5b_acceptance.py`
- [ ] ① Actor 样本库（三 kind）② 三路学习产出候选 ③ 按 actor 切 OOS（LOAO）④ 标准门禁（M3 同门禁）⑤ 自身降级审计 ⑥ 三路一致性作鲁棒性证据（非入库依据）。mock LLM。
- [ ] commit `add m5b acceptance test`

## Task 8: M5b 验证报告
**Files:** `docs/review/2026-06-14-m5b-verification.md`
- [ ] 比照 §4.9 + §11 M5b 出报告。
- [ ] commit `add m5b verification report`

---

## Self-Review
1. **Spec 覆盖**：Actor 抽象+样本库（Task 1）✓ + 三路学习（Task 2-4）✓ + 标准门禁删两路共识（Task 5）✓ + 自身降级（Task 6）✓ + §11 验收（Task 7）✓
2. **设计原则**：标签=PnL 非"是否盈利"防前视；按 actor 切 OOS（LOAO）；偏差声明（游资仅上榜股子集）；删两路共识（同源非独立）；自身小样本降级审计
3. **复用**：M3 Tester（BH-FDR+新颖性+经济）、DSL Sandbox、LLMClient、novelty_check
4. **YAGNI**：机构 actor 可扩展占位；ML 用线性回归简化（不引 sklearn heavy）
5. **跨上下文**：每任务边界更新 memory

## 之后
M6 multi-agent（M3 命题 GO，3b 闭环）→ M4 实盘（Windows）
