# M3 因子挖掘 命题裁决报告

> 日期：2026-06-14　分支：`feat/m3-sentiment-mining`
> 对照：设计 v0.5 §4.3.1（命题：LLM 稳定产出可检验、有 alpha 的因子假设）、§4.3.2（单 agent 闭环）、§4.2.4（五门入库）、§11 M3

---

## 1. 命题（§4.3.1）

**LLM 能否稳定产出「可检验 + 有 alpha」的因子假设？**

即在合成 panel 上，给定研究主题，SingleAgentMine 闭环（LLM → DSL Sandbox →
Interpreter → Tester 五门）能否在固定预算内产出 ≥1 条同时通过
IC≥0.03 / IR≥0.5 / BH-FDR<0.05 / 新颖性 / 经济显著 五门的因子。

---

## 2. 方法

| 项 | 取值 |
|---|---|
| 主题 | 低波动反转 |
| 预算 budget | 15 |
| seed | 11（确定性合成 panel） |
| snapshot_id | `snap_m3_verdict` |
| LLM | 真实 `LLMClient`（火山 Volces Ark / DeepSeek，凭证读 .env） |
| panel | 30 symbol × 60 day，含 close + volume |
| 收益构造 | returns 与 rank(close) 截面排序正相关（slope=0.003），即存在一个**真实可发现**的因子 |
| 门禁 | 默认 TestConfig：IC≥0.03、IR≥0.5、BH-FDR α=0.05、分层多空年化≥0.05、新颖性阈值 0.5 |
| 每轮协议 | agent 逐轮调 `complete_json`，期望 LLM 返回**单条** `{hypothesis, dsl_expr, params, rationale}` |

控制变量：panel 内置一个已知与收益排序正相关的信号（rank(close)），用于测
LLM 能否逼近发现它；volume 与收益独立，用于测是否会产出无 alpha 的噪声因子。

---

## 3. 结果

### 3.1 budget=15 主跑

| 指标 | 值 |
|---|---|
| n_hypotheses（预期） | 15 |
| n_hypotheses（实际完成） | 9（第 10 轮 API 长时挂起，进程 31min 后终止） |
| **n_passed** | **0** |
| n_failures | 9 |
| 失败原因分布 | `llm_parse_error`: 9 |
| 候选 DSL 列表 | （空） |
| OOS IC 分布 | 全部 None（未进入求值阶段） |

### 3.2 budget=2 对照跑

| 指标 | 值 |
|---|---|
| n_hypotheses | 2 |
| **n_passed** | **0** |
| n_failures | 2 |
| 失败原因分布 | `dsl_invalid`: 2 |

对照样本说明：budget 小时 LLM 的输出可被 JSON 解析（取数组首元素），
但产出的 `dsl_expr` 仍不合法（见下根因）。

---

## 4. 裁决：**证伪（M6 暂缓）**

`n_passed == 0`，**命题在当前协议下未被证实**。按规范要求诚实记录，
不粉饰为「接近通过」。

但需明确：**证伪的根因是工程协议缺陷，而非 LLM 固有能力不足**——
因此裁决层级是「M6 multi-agent 暂缓，先修协议」，不是「命题永久证伪」。

### 4.1 根因（budget=15：`llm_parse_error` 9/9）

独立探针捕获的 LLM 原始输出（temperature=0）：

```
[
  {"hypothesis": "过去20日收益为负且波动率低的股票未来20日倾向于反转上涨",
   "dsl_expr": "rank(-ts_mean(return,20)) * rank(-ts_std(return,20))",
   "params": {...}, "rationale": "..."},
  {"hypothesis": "过去5日收益为负且波动率低...", ...},
  ... (共 15 条) ...
]
```

三层复合失效：

1. **提示词协议 vs LLM 行为不匹配**：prompt 写「本轮假设预算：15 条」，
   LLM 据此**一次性返回 15 条假设的 JSON 数组**，而非每轮 1 条。
   agent 却逐轮调用 15 次，每次都被同一个 15 元素数组响应。
2. **max_tokens=1024 截断**：15 条假设的完整 JSON 远超 1024 token，
   输出在数组中途被截断 → JSON 不完整。
3. **`_extract_first_json` 取数组起点 `[` 后做括号配平**：截断的数组
   永远配不平 → `json.loads` 抛 JSONDecodeError → `complete_json`
   抛 ValueError → agent 记 `llm_parse_error`。

### 4.2 根因（budget=2：`dsl_invalid` 2/2）

LLM 输出可解析后，`dsl_expr` 仍被 Sandbox 拒。典型非法形式：

- `rank(-ts_mean(return,20))` —— 一元负号 `-` **非已注册算子**（无 unary neg）
- `*` —— 中缀乘法 **非 DSL 语法**（DSL 用 `mul(...)` 函数式）
- `return` —— **非 panel 字段**（panel 只有 close/volume；return 需在 panel 预算或 prompt 约束）

即 LLM 产的是「自然数学表达式」，与 DSL 注册算子集 + 语法不匹配。

---

## 5. 局限与后续

### 5.1 局限

- **样本量小**：budget=15 实际只完成 9 轮（API 长挂），无法排除「再多跑几轮会偶然产出合法 DSL」的可能。
  但根因是系统性的（每轮都触发同一失效），样本量扩大的预期仍是 0。
- **合成 panel**：30 symbol × 60 day 是最小可测规模；真实 A 股全市场 panel
  下 IC/IR 分布会不同，但 parse/DSL 合法性问题与 panel 无关。
- **单主题**：只测了「低波动反转」；不同主题 LLM 倾向不同，但根因在协议层，
  非主题相关。
- **未测裁判回路**：M3 设计含 judge（§4.3.2），本次只测 hypothesis 生成端，
  judge 端的命题（能否甄别弱因子）未覆盖。

### 5.2 必修（进入 M6 前）

| 优先级 | 项 | 说明 |
|---|---|---|
| P0 | **prompt 改为「每次只产 1 条」** | 删去「本轮假设预算 N 条」诱导；agent 循环本身就是 N 次，prompt 应单条契约 |
| P0 | **max_tokens 提升或截断容错** | 单条假设 JSON 应远小于 1024；若 LLM 仍返回数组，`_extract_first_json` 配平失败时降级取首个 `{...}` 对象 |
| P0 | **DSL 语法对齐** | 一元负号 → `mul(...,-1)` 或新增 `neg`；prompt 示例用函数式 `mul(a,b)`/`add(a,b)` 而非中缀；字段约束为 close/volume |
| P1 | **解析容错增强** | 数组截断时按 `{` 起点重试提取首个对象，而非按 `[` 起点配平整个数组 |
| P1 | **network 测试断言强化** | 现有 `test_real_llm_run` 只断言「不崩 + n_hypotheses 对」，是空断言；应断言「至少 N% 进入合法 DSL 求值阶段」才能守住命题 |

### 5.3 命题后续

- 修完 P0 后**重跑本命题裁决**（同 panel/seed/budget），是 M6 启动的前置门禁。
- 若修复后 n_passed 仍为 0 → 才是真·命题证伪（LLM 即使协议正确也产不出有 alpha 的因子），届时 M6 重新评估。
- 若修复后 n_passed>0 → 命题 go，进 M6 multi-agent（多 agent 提假设 + judge 筛选 + 演化）。

---

## 6. 结论

| 维度 | 结论 |
|---|---|
| §11 M3 工程 Done | ✅ 验收 6/6 绿（mock LLM 确定性），DSL/Sandbox/Tester/Agent/Tracker/breadth 全部可用 |
| §4.3.1 命题（真实 LLM） | ❌ 证伪（n_passed=0），根因为工程协议缺陷，非 LLM 固有 |
| M6 multi-agent | ⏸ 暂缓，先修 P0 协议项后重跑本裁决为前置门禁 |

**工程层 M3 完成；命题层在当前协议下未通过诚实裁决，根因明确可修。**
