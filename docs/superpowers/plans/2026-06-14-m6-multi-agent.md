# M6 multi-agent 因子挖掘 + 情绪二期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking. 实现与审查分离。**跨多上下文窗口；每任务边界更新 memory。LLM 读 .env（DashScope）。**

**Goal:** 交付 §4.3.1 3b multi-agent 闭环（Hypothesizer→Composer→Tester→Judge→Iterator，状态落 agent_run 可恢复，≥50 轮）+ §4.1.2 情绪二期框架（社媒，合规开关默认关，需用户显式知情开启）。M3 命题已 GO（M6 可启动）。

**Architecture:** multi-agent 角色化为独立 Agent（各持 LLMClient 角色 prompt），orchestrator 驱动闭环（Hypothesizer 产假设 → Composer DSL 求值 → Tester M3 门禁 → Judge 裁决入库/归档/迭代 → Iterator 决定下一轮方向）。状态落 agent_run 表（M0 schema）每轮 checkpoint，可从任意轮恢复。子进程沙箱：M6 仍用 M3 DSL 沙箱（主路径）；若 LLM 产 Python 源码则子进程+超时（占位接口）。情绪二期：SentimentProviderV2 抽象 + 合规开关（默认关）+ stub 抓取器（真实社媒抓取合规敏感，留用户显式开启）。

**Tech Stack:** Python 3.11+ · 复用 M3（DSL/LLMClient/Tester/ExperimentTracker/Sandbox）。无新依赖

**关联：** §4.3.1（3b multi-agent）、§4.3.2（实验追踪/agent_run）、§4.1.2（情绪二期社媒）、§11 M6

**前置：** M0-M1.5+M3+M-1b/M2+M5a/M5b 完成（main）。本计划在 `feat/m6-multi-agent`。

**验收标准（设计 §11 M6）：**
1. multi-agent 闭环可恢复 ≥ 50 轮（断点恢复）
2. 社媒因子增量贡献显著（用户显式开启后）——本计划建框架+开关，真实社媒留用户开启

---

## File Structure

```
quant/
├── mining/
│   ├── multi_agent.py        # MultiAgentOrchestrator + 5 角色（Hypothesizer/Composer/Tester/Judge/Iterator）
│   ├── agent_state.py        # agent_run 状态 checkpoint/恢复（M0 agent_run 表）
│   └── sandbox_subprocess.py # 子进程沙箱（LLM 产 Python 源码时，占位+超时）
├── factors/
│   └── sentiment_v2.py       # 情绪二期：SentimentProviderV2 + 合规开关（默认关）+ stub 抓取
tests/quant/test_multi_agent_*.py / test_sentiment_v2.py（扁平）
```

---

## Task 1: Agent 状态 checkpoint/恢复
**Files:** `quant/mining/agent_state.py`, `tests/quant/test_multi_agent_state.py`
- [ ] AgentState（run_id/round/phase/status/state_json）落 agent_run 表（M0 schema）；checkpoint(run_id, round, phase, state)；resume(run_id)→最新 checkpoint。幂等可恢复。
- [ ] 测试：checkpoint 落库；resume 读最新；多轮 checkpoint 历史。
- [ ] commit `add multi-agent state checkpoint and resume`

## Task 2: 5 角色 Agent
**Files:** `quant/mining/multi_agent.py`, `tests/quant/test_multi_agent_roles.py`
- [ ] Hypothesizer/Composer/Tester/Judge/Iterator 各角色（角色 prompt + 职责）。Composer 用 M3 DSL 解释器求值；Tester 复用 M3 Tester；Judge 裁决（入库/归档/迭代）；Iterator 决定下一轮方向（基于上轮结果）。
- [ ] 测试：各角色输入输出契约；Composer 复用 DSL；Tester 复用 M3；Judge 裁决逻辑；mock LLM。
- [ ] commit `add multi-agent roles`

## Task 3: Multi-agent orchestrator（≥50 轮可恢复）
**Files:** `quant/mining/multi_agent.py`（扩）, `tests/quant/test_multi_agent_orchestrator.py`
- [ ] MultiAgentOrchestrator.run(topic, panel, max_rounds=50, resume_from=None)：驱动闭环，每轮 checkpoint（agent_state），异常/中断可 resume_from 恢复。通过因子入候选库 + Tracker 落 experiment。
- [ ] 测试：跑 N 轮（mock LLM，小 max_rounds 验证可恢复）；中途 checkpoint → resume_from 续跑；≥轮数控制；mock LLM。
- [ ] commit `add multi-agent orchestrator with recovery`

## Task 4: 子进程沙箱（占位）
**Files:** `quant/mining/sandbox_subprocess.py`, `tests/quant/test_sandbox_subprocess.py`
- [ ] SubprocessSandbox.run(code, timeout)：子进程执行 LLM 产的 Python 源码（若 3b 需要），超时 kill。M6 主路径用 DSL（M3），子进程沙箱为可选路径（占位+测试，真实使用留后续）。
- [ ] 测试：简单代码子进程返回；超时 kill；异常隔离。
- [ ] commit `add subprocess sandbox placeholder`

## Task 5: 情绪二期（框架+合规开关）
**Files:** `quant/factors/sentiment_v2.py`, `tests/quant/test_sentiment_v2.py`
- [ ] SentimentProviderV2 + 合规开关（compliance_switch 默认 False；用户显式知情开启才激活）。Stub 抓取器（占位接口，真实社媒抓取合规敏感留用户开启）。聚合指标（讨论数/关键词词频，不存可识别个人内容，§4.1.2/§16 合规）。
- [ ] 测试：开关默认关→禁用；显式开→激活 stub；聚合指标计算；合规注释。
- [ ] commit `add sentiment v2 framework with compliance switch`

## Task 6: §11 M6 集成验收
**Files:** `tests/quant/test_m6_acceptance.py`
- [ ] ① multi-agent 闭环跑 N 轮（mock LLM）② checkpoint/resume 断点恢复（跑到 K 轮中断→resume 续到 N）③ 5 角色协作产出候选 ④ 情绪二期开关默认关/显式开 ⑤ 因子经标准门禁入库 ⑥ ≥50 轮可达（用小 max_rounds 验证机制，注释说明 50 轮同等）。
- [ ] commit `add m6 acceptance test`

## Task 7: M6 验证报告
**Files:** `docs/review/2026-06-14-m6-verification.md`
- [ ] 比照 §4.3.1 3b + §4.1.2 + §11 M6 出报告。
- [ ] commit `add m6 verification report`

---

## Self-Review
1. **Spec 覆盖**：multi-agent 闭环（Task 1-3）✓ + 子进程沙箱占位（Task 4）✓ + 情绪二期框架（Task 5）✓ + §11 验收（Task 6）✓
2. **设计原则**：状态落 agent_run 可恢复（§4.3.2）；DSL 主沙箱（M3），子进程为可选；情绪二期合规开关默认关（§4.1.2/§16）；复用 M3 Tester/DSL/LLMClient
3. **复用**：M3 全部（DSL/Tester/Tracker/LLMClient/Sandbox）
4. **YAGNI**：真实社媒抓取留用户开启；子进程沙箱占位；Iterator 策略简化
5. **跨上下文**：每任务边界更新 memory

## 之后
M4 实盘（Windows + QMT）—— 所有本地可建里程碑（M0-M1.5+M3+M-1b/M2+M5a/M5b+M6）届时全部就位
