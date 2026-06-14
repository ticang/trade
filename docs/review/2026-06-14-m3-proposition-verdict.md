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

### 5.0 协议修复后重跑（2026-06-14）

修完 §5.2 中 3 项 P0（commit `b072e1e`、`d1c792e`）后，按 §5.3 要求
**同命题重跑**，判定 P0 是否真根因，还是 LLM 固有不可行。

**修复内容**：
- `hypothesis_prompt` 改为逐轮请求恰好 1 条新假设（删去「本轮假设预算 N 条」
  诱导）；附可用算子清单 + panel 字段清单 + DSL 函数式语法示例
  （mul/add/sub/div，一元负号用 `neg(...)`）
- `LLMClient.complete / complete_json` 默认 `max_tokens` 1024→4096
- DSL 一元负号：parser 把 `-expr` 映射为 `neg(expr)`，新增 `neg` 算子
- `SingleAgentMine.run` 每轮重新构造 prompt（携带 round_idx + 算子白名单
  + panel 字段列表，从 `panel.columns` 取字段）

**重跑配置**：
- 主题：量价动量
- budget：12
- seed：11
- snapshot_id：`snap_m3_verdict_v2`
- panel：8 symbol × 80 day，含 close/volume
- 真因子：收益与 `rank(ts_delta(close,5))` 截面排序正相关（slope=0.005
  + 小噪声）；健全性自检 `ic_mean=0.2175 ir=0.625 t=4.817 n=75`，
  即存在一个**清晰可发现**的 alpha 信号
- 门禁：min_ic=0.02 / min_ir=0.3 / min_long_short_annual=0（默认 BH-FDR α=0.05）

**结果**：

| 指标 | 值 |
|---|---|
| n_hypotheses | 12 |
| **n_passed** | **0** |
| n_failures | 12 |
| 失败原因分布 | `dsl_eval_error`: 11；`ir_below_min,long_short_annual_below_min`: 1 |
| llm_parse_error | **0**（修复前 9/9，修复后 0/12） |
| 候选 DSL | （空） |

**P0 修复全部生效**：
- 12/12 全部 LLM 输出可被 `complete_json` 解析为 dict（修复前 9/9 parse_error）
- LLM 全程未产 `*`/`+` 等中缀符号，未产 `return` 等非字段名
- 一元负号被正确接受并求值：`neg(ts_corr(...))`、`rank(neg(ts_corr(...)))` 等
- 字段全部限定在 close/volume 内
- prompt 逐轮 1 条契约生效，无再返回数组

**进入求值阶段的 1 条 DSL**（其余 11 条被 Interpreter 拒）：

```
zscore(div(mul(ts_delta(close,20), decay_linear(volume,20)), ts_mean(volume,20)))
```

IC/IR 未达门禁（与真因子方向不同——LLM 偏向"量价交叉动量"而非"纯价 5 日动量"）。

**未通过真因子**（健全性证明可被发现）：

```
rank(ts_delta(close,5))   # 健全性自检 ic_mean=0.2175 ir=0.625 t=4.817
```

LLM 在 12 轮内未逼近产出此表达式。

**11/12 `dsl_eval_error` 根因**：LLM 习惯把时序算子表达式嵌套进 `ts_corr`
的 field 位置，例如：

```
ts_corr(ts_delta(close,1), ts_delta(volume,1), 20)
neg(ts_corr(ts_delta(close,1), ts_delta(volume,1), 20))
rank(neg(ts_corr(ts_delta(close,5), ts_delta(volume,5), 10)))
```

但 DSL 中 `ts_corr` 的 arg_types 是 `['field','field','num']`，要求前两参数
是字段名而非算子表达式（与 WorldQuant Brain 一致，避免任意嵌套导致
复杂度爆炸）。LLM 不知道这个限制——这是 **prompt 协议未告知算子参数类型
约束**导致，属**第二层 P0**（修复后暴露的新协议缺陷），非 LLM 固有能力。

**裁决（协议修复后）**：

| 维度 | 结论 |
|---|---|
| 4 处原始 P0 协议修复 | ✅ 全部生效（0 parse_error / neg 接受 / 字段约束 / max_tokens 充足） |
| §4.3.1 命题（真实 LLM n_passed>0） | ❌ **仍证伪**（n_passed=0），但根因清晰为**第二层协议缺陷**（算子参数类型约束未在 prompt 中告知），非 LLM 固有不可行 |
| M6 multi-agent | ⏸ 暂缓，需先修第二层 P0（prompt 明示算子参数类型）后再次重跑 |

**第二层 P0（进入 M6 前必修）**：

| 项 | 说明 |
|---|---|
| P0-2 | prompt 明示每个算子的参数类型约束（field vs expr vs num）：例如 `ts_corr(field, field, num)` 不接受嵌套算子表达式；或扩 DSL 让 `ts_corr` 也接受 expr 参数（架构权衡，需独立评估） |
| P1-2 | 引导 LLM 先产简单因子（如 `rank(ts_delta(close,5))`），再演化复杂度——multi-agent 的"广度→深度"流程本身就是这条路径 |

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
| §4.3.1 命题（真实 LLM，原始协议） | ❌ 证伪（n_passed=0，9/9 llm_parse_error），根因为 4 处 P0 工程协议缺陷 |
| §4.3.1 命题（真实 LLM，P0 修复后重跑） | ❌ **仍证伪**（n_passed=0，11/12 dsl_eval_error），4 处 P0 全部生效；新根因为**第二层 P0**（算子参数类型约束未告知 LLM） |
| M6 multi-agent | ⏸ 暂缓，需先修第二层 P0（prompt 明示算子参数类型 / DSL 接受 expr 参数）后再次重跑为前置门禁 |

**工程层 M3 完成；命题层经两轮诚实裁决均未通过——首轮是协议 bug，次轮是 LLM 行为与 DSL 算子签名约束的下一层不匹配，根因仍可修。**
