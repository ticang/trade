# M5b 主体行为学习层 验证报告

> 日期：2026-06-14　分支：`feat/m5b-actor-learning`
> 对照：设计 v0.5 §4.9.1（Actor 抽象）、§4.9.2（数据源偏差）、§4.9.3（三路学习）、§4.9.4（标准门禁）、§4.9.5（自身降级）、§11 M5b

---

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **576 passed, 1 xfailed, 6 deselected** |
| M5b 验收（test_m5b_acceptance） | 9/9 绿（+1 network），确定性（seed=2024） |

---

## 2. §11 M5b 验收

| # | 验收条 | 实现 | 证据 |
|---|---|---|---|
| 1 | Actor 样本库（三 kind） | SampleLibrary（SELF/HOT_MONEY/NORTHBOUND/INSTITUTION + 偏差声明） | test_m5b_sample_library_multi_kind |
| 2 | 三路学习产出候选 | stat_profile + AIInduct + MLImitate | test_m5b_three_paths_produce_candidates |
| 3 | 按 actor 切 OOS（LOAO） | MLImitate.fit_loao（Leave-One-Actor-Out，标签=PnL） | test_m5b_ml_loao_oos |
| 4 | 标准门禁（M3 同门禁） | ActorGate 复用 M3 Tester（BH-FDR+新颖性+经济） | test_m5b_standard_gate_reuses_m3 |
| 5 | 一致性作鲁棒性证据（非入库） | method_consistency 不门控，删"两路共识"（§4.9.4） | test_m5b_consistency_evidence_only |
| 6 | 自身降级审计 | SelfAudit（追高/割肉/持仓过久/频繁 + 小样本标注） | test_m5b_self_audit_degraded |

---

## 3. 组件 vs 设计

### §4.9.1-4.9.2 Actor + 数据源
- ✅ ActorKind（4 种）、ActorTrade（symbol/time/side/price/volume/realized_pnl/context）、SampleLibrary（按 kind 聚合 + **偏差声明**：HOT_MONEY 仅上榜股子集 + 小样本检测）

### §4.9.3 三路并行学习
- ✅ **统计画像**（胜率/盈亏比/持仓周期/板块偏好/买卖点特征）
- ✅ **AI 归纳**（LLM 读样本归纳高胜率条件 → 候选 DSL，真实 LLM 为 HOT_MONEY 产 2 经济逻辑候选）
- ✅ **ML 模仿**（**标签=实现 PnL 非"是否盈利"防前视**，特征 PIT，**按 actor 切 OOS LOAO**，线性回归）

### §4.9.4 入库门禁
- ✅ ActorGate 复用 M3 标准 Tester（样本外+BH-FDR+新颖性+经济+人审）；**删"两路共识即入库"**（同源非独立，method_consistency 作鲁棒性证据非门控）

### §4.9.5 自身画像降级
- ✅ SelfAudit（小样本→交易行为审计+规则化提醒：追高/割肉/持仓过久/频繁，非建模对象）

---

## 4. 设计原则落实

- **标签防前视**（§4.9.3）：ML 标签=actor 实现 PnL（连续值），非"是否盈利"二元
- **按 actor 切 OOS**（§4.9.3）：LOAO——某 actor 训练则该 actor 全期 OOS，不按时间切
- **偏差声明**（§4.9.2）：游资仅上榜股子集，HOT_MONEY 默认 bias_note
- **删两路共识**（§4.9.4）：同源数据非独立，一致性仅鲁棒性证据
- **复用 M3**：Tester/DSL Sandbox/LLMClient/novelty 全复用（M3 同门禁）

---

## 5. 已知延后

| 项 | 归属 |
|---|---|
| 机构 actor 实际数据接入 | 当前 ActorKind.INSTITUTION 占位 |
| ML 用线性回归（不引 sklearn） | YAGNI；增强模型留后续 |
| AI 归纳 novelty 用 DSL 字串归一化 | 假设阶段无 panel，值-based 留 panel 接入时 |
| 真实龙虎榜/北向数据接入 | 数据源 M0 基础数据层扩展 |

---

## 6. 结论

**M5b 主体行为学习层全部实现并通过 §11 M5b 验收**（576 测试绿，确定性）。Actor 抽象 + 三路并行学习（统计/AI/ML，标签=PnL，LOAO）+ 标准门禁（复用 M3，删两路共识）+ 自身降级审计就位。系统行为学习能力完整。可进入 M6（multi-agent，M3 命题已 GO）或 M4 实盘（Windows）。
