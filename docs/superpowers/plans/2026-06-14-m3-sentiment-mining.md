# M3 情绪一期 + 单 agent 因子挖掘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking. 实现与审查分离。**跨多上下文窗口；每任务边界更新 memory。凭证读 .env（gitignored），禁入代码。**

**Goal:** 交付 §4.3.1 的 3a 单 agent 因子挖掘闭环（LLM 假设 → DSL 表达式 → Tester 全门禁 → Judge → 入库/归档）+ §4.1.2 情绪一期（市场宽度因子，诚实定位非散户情绪反向）+ 实验追踪落库。M3 末做命题裁决（go/no-go）。

**Architecture:** LLM 客户端连火山 Volces Ark（OpenAI 兼容，承载 DeepSeek）。DSL 手写解释器沙箱（M-1a 验证路线，扩算子集）。单 agent：Hypothesizer（LLM 产假设+DSL）→ Composer（解释器算因子值）→ Tester（M1 因子评价 rank IC/IR/新颖性 + BH-FDR + 经济显著）→ Judge（裁决入因子库 or 归档）。情绪一期：从 bar 自算市场宽度（涨跌停家数/连板高度/封板率）。实验每次落 `experiment` 表（M0 schema）含 snapshot_id。

**Tech Stack:** Python 3.11+ · openai SDK（Volces Ark 兼容）· 复用 M0/M0.5/M1/M1.5。新依赖：`openai>=1.0`

**关联：** §4.3.1（3a）、§4.3.2（实验追踪）、§4.3.3（DSL 算子集）、§4.1.2（情绪一期）、§4.2.4（防过拟合 BH-FDR/双门）、§11 M3

**前置：** M0+M0.5+M1+M1.5 完成（main）。本计划在 `feat/m3-sentiment-mining`。

**验收标准（设计 §11 M3）：**
1. 工程 Done：管线端到端可复现、门禁生效、实验落库
2. 命题裁决（go/no-go 报告）：通过全门禁因子数、OOS IC 分布、与已知因子相关性；0 因子 → M6 暂缓

---

## File Structure

```
quant/
├── dsl/
│   ├── __init__.py
│   ├── operators.py            # 时序/横截面/分组/算子（§4.3.3 算子集）
│   ├── interpreter.py          # 手写解释器（tokenizer/parser/eval，PIT 安全）
│   └── sandbox.py              # 沙箱边界（算子集=边界，超时/资源限制）
├── llm/
│   ├── __init__.py
│   ├── client.py               # Volces Ark OpenAI 兼容客户端（读 .env）
│   └── prompt.py               # 假设生成/裁决 prompt 模板
├── mining/
│   ├── __init__.py
│   ├── agent.py                # 单 agent 闭环（Hypothesizer→Composer→Tester→Judge）
│   ├── tester.py               # Tester（接 M1 eval：rank IC/IR/新颖性 + BH-FDR + 经济显著）
│   └── tracker.py              # 实验追踪（落 experiment 表）
├── factors/
│   └── breadth.py              # 情绪一期：市场宽度因子（涨跌停家数/连板/封板率）
tests/quant/test_dsl_*.py / test_llm_*.py / test_mining_*.py / test_breadth.py（扁平）
```

---

## Phase A：DSL 生产解释器

### Task A1: 算子集（时序+横截面+分组+算术）
**Files:** `quant/dsl/operators.py`, `tests/quant/test_dsl_operators.py`
- [ ] 时序（per symbol rolling，§4.3.3）：`delay/ts_mean/ts_std/ts_rank/ts_max/ts_delta/ts_corr/decay_linear`。横截面：`rank/zscore/quantile/winsorize/scale`。分组：`group_neutral`。算术：`+,-,*,/,signed_power`。
- [ ] 全向量化 pandas/numpy；长格式 panel（symbol/trade_date/<fields>）。
- [ ] 测试：每算子对照 pandas 参考（如 ts_mean(close,5) = groupby symbol rolling 5 mean）。
- [ ] commit `add dsl operator set`

### Task A2: 解释器（tokenizer/parser/eval）+ 沙箱
**Files:** `quant/dsl/interpreter.py`, `quant/dsl/sandbox.py`, `tests/quant/test_dsl_interpreter.py`
- [ ] 手写递归下降解析：`func(arg, arg)` 嵌套、字段名、数字、算术。eval 在长格式 panel 上向量化。未知算子/超算子集 → 拒（沙箱边界）。复用 M-1a 探测的 tokenizer 思路扩算子。
- [ ] 测试：复合表达式（如 `rank(ts_delta(close,5))`）对照 pandas；未知算子抛；嵌套正确。
- [ ] commit `add dsl interpreter and sandbox`

---

## Phase B：LLM 客户端 + 单 agent 闭环

### Task B1: LLM 客户端（Volces Ark）
**Files:** `quant/llm/client.py`, `quant/llm/prompt.py`, `tests/quant/test_llm_client.py`
- [ ] **装 openai**：`.venv/bin/pip install --index-url https://pypi.org/simple openai`，pyproject 加 `openai>=1.0`。
- [ ] `LLMClient`：读 .env（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL，经 os.environ），OpenAI 兼容 chat.completions。`complete(messages, **kw) -> str`。temperature=0 默认（§4.3.2 复现性）。
- [ ] prompt 模板：假设生成（产 JSON{hypothesis, dsl_expr, params}）、裁决。
- [ ] 测试：mock OpenAI client（不真实调）；complete 解析正确；.env 缺 key 抛清晰错。**真实 API 调用标 @pytest.mark.network**（deselect 默认，手动验证）。
- [ ] commit `add llm client for volces ark`

### Task B2: Tester（全门禁）
**Files:** `quant/mining/tester.py`, `tests/quant/test_mining_tester.py`
- [ ] `Tester.test(factor_values, forward_returns, industry, mktcap, hypothesis_budget)`：复用 M1 eval（rank IC 中性化/IR-NW/新颖性/分层）。**BH-FDR**（分母用 hypothesis_budget 预算数，§4.2.4）+ **经济显著**（IC≥0.03/IR≥0.5/分层多空扣费年化≥阈值）。返回 TestResult(passed, ic, ir, novelty, bh_fdr_p, reasons)。
- [ ] 测试：合成强因子通过门禁；随机因子拒；新颖性高（与已知因子相关>0.5）拒；BH-FDR p 计算。
- [ ] commit `add factor tester with bh-fdr and economics gate`

### Task B3: 实验追踪
**Files:** `quant/mining/tracker.py`, `tests/quant/test_mining_tracker.py`
- [ ] `ExperimentTracker.log(store, run_id, kind, hypothesis, expr, params, hypothesis_budget, n_tests, llm_model, seed, snapshot_id, oos_ic)`：写 experiment 表（M0 schema）。查询/归档。
- [ ] 测试：log 落库；查询往返；snapshot_id 记录。
- [ ] commit `add experiment tracker`

### Task B4: 单 agent 闭环
**Files:** `quant/mining/agent.py`, `tests/quant/test_mining_agent.py`
- [ ] `SingleAgentMine.run(topic, panel, hypothesis_budget, seed)`：循环 budget 次：LLM 产假设+DSL → Composer（interpreter 算因子值）→ Tester（门禁）→ Tracker 落库 → 通过者入候选库。状态可恢复（agent_run 表，M0 schema）。
- [ ] 测试：mock LLM 返回固定 DSL，闭环跑通（产假设→测→落库）；门禁拒的不入库；可恢复。**真实 LLM 标 network**。
- [ ] commit `add single agent mining loop`

---

## Phase C：情绪一期（市场宽度）

### Task C1: 市场宽度因子
**Files:** `quant/factors/breadth.py`, `tests/quant/test_breadth.py`
- [ ] `breadth_factors(bars_panel)`：从 bar 自算（§4.1.2 一期诚实化）：涨跌停家数、连板高度分布、封板率（可由行情自算）。**不宣称散户情绪反向**（一期定位=市场宽度因子工程）。北向/两融标"不宜反向"（注释）。
- [ ] 测试：合成多 symbol bar（含涨停），算 breadth 指标对照手算。
- [ ] commit `add market breadth factors`

---

## Phase D：§11 M3 集成验收 + 命题裁决

### Task D1: 集成 + 命题裁决报告
**Files:** `tests/quant/test_m3_acceptance.py`, `docs/review/2026-06-14-m3-proposition-verdict.md`
- [ ] 验收：① 管线端到端可复现（同 seed+snapshot 二次跑一致）② 门禁生效（强因子入库/随机拒）③ 实验落库 ④ DSL 算子集边界（未知算子拒）⑤ 情绪一期 breadth 可算。
- [ ] **命题裁决报告**（§4.3.1）：跑 N 假设（真实 LLM，network），统计通过全门禁因子数/OOS IC 分布/新颖性；0 因子 → 命题证伪 → M6 暂缓（诚实记录）。
- [ ] commit `add m3 acceptance and proposition verdict`

---

## Self-Review
1. **Spec 覆盖**（§11 M3）：DSL 解释器（A）✓ + 单 agent 闭环（B）✓ + 实验追踪（B3）✓ + 情绪一期市场宽度（C）✓ + §11 验收+命题裁决（D）✓
2. **诚实定位**：一期市场宽度非散户情绪反向（§4.1.2）；命题裁决 go/no-go（§4.3.1）
3. **防过拟合**：BH-FDR 分母用预算数（§4.2.4）+ 锁死 holdout + 新颖性双查 + 双门（统计+经济）
4. **复用 M1/M1.5**：eval（rank IC/IR/新颖性/分层）、FactorRegistry、snapshot、BacktestEngine 摩擦（扣费年化）
5. **凭证安全**：LLM key 读 .env（gitignored），禁入代码；network 测试 deselect 默认
6. **新依赖**：openai SDK
7. **跨上下文**：每任务边界更新 memory

## M3 之后
M-1b/M2（xtquant 通道，Windows）→ M4 实盘 → M5 情景+主体学习 → M6 multi-agent（依赖 M3 命题 go）
