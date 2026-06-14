# M6 multi-agent + 情绪二期 验证报告

> 日期：2026-06-14　分支：`feat/m6-multi-agent`
> 对照：设计 v0.5 §4.3.1（3b multi-agent）、§4.3.2（agent_run 可恢复）、§4.3.3（子进程沙箱）、§4.1.2（情绪二期）、§16（合规）、§11 M6

---

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **625 passed, 1 xfailed, 6+ deselected** |
| M6 验收（test_m6_acceptance） | 8/8 绿，确定性（mock LLM，固定 seed） |

---

## 2. §11 M6 验收

| # | 验收条 | 实现 | 证据 |
|---|---|---|---|
| 1 | multi-agent 闭环可恢复 ≥ 50 轮 | MultiAgentOrchestrator（max_rounds=50 验证）+ checkpoint/resume | test_m6_fifty_rounds_mechanism, test_m6_checkpoint_resume_recovery |
| 2 | 5 角色协作产出候选 | Hypothesizer→Composer→TesterRole→Judge→Iterator | test_m6_five_roles_collaborate |
| 3 | 因子经标准门禁入库 | Judge 复用 M3 Tester（BH-FDR+新颖性+经济） | test_m6_standard_gate_factors |
| 4 | 社媒因子增量（用户显式开启） | SentimentProviderV2 框架 + 合规开关默认关 + stub | test_m6_sentiment_v2_default_off/explicit_enable |

---

## 3. 组件 vs 设计

### §4.3.1 3b multi-agent 闭环
- ✅ AgentStateStore（agent_run 表 checkpoint/resume，幂等可恢复）
- ✅ 5 角色（Hypothesizer LLM 假设 / Composer M3 DSL 求值 / TesterRole M3 门禁 / Judge 裁决 accept-archive-iterate / Iterator 下一轮方向）
- ✅ MultiAgentOrchestrator（≥50 轮闭环，每轮 checkpoint，resume_from 断点恢复，ExperimentTracker 落库）

### §4.3.3 子进程沙箱（可选）
- ✅ SubprocessSandbox（占位：子进程执行 LLM Python 源码 + 超时 kill；M6 主路径用 M3 DSL，子进程为可选；生产 seccomp/nsjail 留后续）

### §4.1.2 + §16 情绪二期
- ✅ SentimentProviderV2 + ComplianceConfig（**合规开关默认关**，需 enabled AND user_acknowledged AND NOT store_personal_content；force 不可绕过；匿名化聚合剥离个人内容；CJK 2-gram 主题词；stub 抓取，真实社媒留用户显式开启）

---

## 4. 设计原则落实

- **状态落库可恢复**（§4.3.2）：agent_run 每轮 checkpoint，resume_from 任意轮恢复
- **DSL 主沙箱**（§4.3.3）：M6 复用 M3 DSL；子进程为 LLM 源码可选路径
- **合规开关默认关**（§4.1.2/§16）：情绪二期三条件 AND，不存个人内容，用户显式知情开启
- **复用 M3**：Tester/DSL/LLMClient/ExperimentTracker 全复用（M3 命题 GO 的延续）

---

## 5. 已知延后

| 项 | 归属 |
|---|---|
| 真实社媒抓取（抖音/小红书/微博） | 合规敏感，留用户显式开启后接入 |
| 子进程 seccomp/nsjail 强隔离 | 占位，留后续 |
| Iterator 高级策略 | 当前简化查表，留后续 |
| 真实 50 轮 LLM 跑（非 mock） | mock 验证机制；真实跑需 LLM 配额/时间 |

---

## 6. 结论

**M6 multi-agent + 情绪二期全部实现并通过 §11 M6 验收**（625 测试绿，确定性）。multi-agent 5 角色闭环可恢复 ≥50 轮 + 子进程沙箱占位 + 情绪二期合规框架就位。

## 🏁 全里程碑总览（M0 → M6）

本地可建里程碑**全部完成**：
- M0 基础设施 / M0.5 交易规则 / M1 因子+回测 / M1.5 策略+组合优化
- M3 单 agent 挖掘（命题 GO）/ M-1b/M2 xtquant 通道+模拟盘（代码+mock，live 待 Windows）
- M5a 情景模拟与复盘 / M5b 主体行为学习 / **M6 multi-agent + 情绪二期**

**唯一剩余：M4 实盘**（严肃风控/拆单/影子→小资金/一致性/灰度）—— 依赖 **Windows + QMT 客户端登录态**，所有代码基础已就位。
