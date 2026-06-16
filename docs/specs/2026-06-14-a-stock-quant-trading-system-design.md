# A 股量化自动交易系统 — 需求分析与设计

> 版本: v0.5  ·  日期: 2026-06-14  ·  状态: 设计评审中
>
> **修订要点**（v0.5 吸收四维度独立红队审阅，详见 `docs/review/2026-06-14-v04-redteam-4dim-review.md`）：
> ① **一期宣称诚实化**：一期 = 因子工程管线 + 市场宽度/资金流因子（非反向）；散户情绪反向作为二期 alpha 目标；北向/两融标注"不宜作反向源"；② **当前阶段仅做沪深主板股票**，风控结算按主板 T+1 落地，TradingRuleProvider 保留 per-product T+N 扩展口；③ **多账户**一期支持（position/orders/fills 加 account_id，Broker per-account）；④ **因子评价**强制行业/市值中性化残差 + rank IC + Newey-West + 经济显著性双门 + 新颖性 0.5-0.7；⑤ **PIT 可复现性**引入 `factor_snapshot_id`（冻结数据快照），区分代码版本/数据快照，区分实时段（可证）/回填段（`pit_confidence=rule_inferred`）；⑥ **组合优化**明确标量化公式 + λ/γ + 基准 + QP-vs-整数化 gap + 求解器命名；⑦ **情景模拟**改 GARCH/EGARCH-t + DCC 动态相关，路径强制过撮合模拟器；⑧ **行为学习**标签=actor 实现 PnL、龙虎榜标"仅高波动子集"、删"两路共识入库"、按 actor 切 OOS；⑨ **分层并发**：因子/策略 offload ProcessPool、网关背压、SQLite 写独立线程、DuckDB 单写进程交接；⑩ **沙箱**改 DSL 手写解释器路线（删 RestrictedPython 主沙箱）；⑪ **M-1 拆 M-1a（本地）/M-1b（外部通道）**；⑫ **TradingRuleProvider 升级独立子模块 M0.5**；⑬ 新增 **§16 数据合规清单**；⑭ 补止损止盈/策略生命周期/再平衡频率/进程内事件总线/bar 去重/策略隔离；⑮ 移除 APScheduler；⑯ §15 URL 加状态列、过户费改 provisional。

---

## 0. 摘要

构建一套面向 A 股的多策略可插拔量化交易平台，**当前阶段只覆盖沪深主板股票**，按“技术探测 → 回测校准 → 模拟盘 → 小资金实盘”分阶段演进，支持**单用户多券商账户**。一期差异化能力为 **agent 因子挖掘管线（M3 单 agent 起步，M6 multi-agent 增强）+ 市场宽度/资金流因子**；散户情绪反向作为二期 alpha 目标（依赖社媒采集合规放行）。同时扩展 **情景模拟复盘** 与 **主体行为学习** 两条迭代闭环（M5）。起步采用零独立中间件的分层单体架构（SQLite + DuckDB + asyncio），通过 Repository / Provider 抽象保证迁移路径。所有外部数据和交易规则以 **point-in-time 语义** 约束（区分实时段可证 / 回填段推断），回测 / 模拟 / 实盘在接口层共用、在撮合层显式建模偏差。

---

## 1. 背景与目标

### 1.1 背景

参考资料 (`资料.docx` / `docs/reference-notes.md`) 的实战经验提炼：

- **multi-agent 因子挖掘**：自动挖掘 alpha 因子，选出相对大概率上涨的标的，迭代生成新因子（原资料仅一句口头描述，工程结构为本设计推断）。
- **散户情绪反向**：散户是对手盘，反方向思考容错率更大；针对特殊节点行情定制策略 + 结合情绪，收益爆发式但生命周期短。
- **情绪数据来源**：抖音 / 小红书 / 微信群 / 热门博主评论区（含合规风险，分期处理）。
- **可视化范式**：价格 + 成交量 + 散户情绪曲线三合一。

### 1.2 目标

| 目标 | 说明 |
|---|---|
| 分阶段落地 | 技术探测 → 模拟盘 → 实盘；回测 / 模拟 / 实盘接口层共用 |
| 多策略可插拔 | 统一策略接口与因子库，多策略并行、信号仲裁、组合优化 |
| 一期差异化 | **因子工程管线（M3 单 agent 起步，M6 multi-agent 增强）+ 市场宽度/资金流因子**；散户情绪反向作二期目标 |
| 两条迭代闭环 | 情景模拟复盘（M5a）+ 主体行为学习（M5b） |
| 风控分层 | 服务"个人小资金"与"中等规模严肃"两档，**支持多券商账户** |
| 基础交易完整 | 止损止盈、策略生命周期管理、再平衡频率 |

### 1.3 非目标（明确排除）

- 不做高频 / Tick 级做市（面向分钟级及以上，决策链路目标秒级）。
- 不做跨市场（当前仅沪深主板股票；港股/美股/期货不在范围）。
- 不在当前阶段覆盖科创板、创业板、北交所、ETF、可转债、B 股；这些作为后续扩展，需补规则 fixture 后再进入实盘范围。
- 不做面向多租户的 SaaS（**单用户多账户**，非多用户）。
- 不使用融资融券 / 杠杆（默认现货；当前主板股票按 **T+1**，后续品种再按规则表扩展 T+N）。
- 不在首期实现社媒私域爬取（合规开关默认关闭）。

### 1.4 资金档位（与开户门槛解耦 + 档内分档）

> 资金档位与 MiniQMT 开户门槛是两个独立维度，不共用同一数字（门槛由 M-1b 实测，国金类低门槛券商 ~10 万可开，头部 ~50 万）。

| 档位 | 区间 | 风控档 | 基础设施 | 子档（严肃层参数缩放） |
|---|---|---|---|---|
| 小资金练手 | < 50 万 | 基础层 | 单机 SQLite+DuckDB，无拆单，单 as_of+修订日志 | — |
| 中等规模 A | 50 万 – 200 万 | 基础 + 严肃层 | 单机 + TWAP/VWAP + 监控告警 | 单票≤15%、行业暴露≤30%、流动性占比≤10% |
| 中等规模 B | 200 万 – 1000 万 | 基础 + 严肃层 | 单机 + 拆单 + 多账户 + 告警 | 单票≤8%、行业暴露≤25%、流动性占比≤5% |
| （>1000 万） | — | — | 需分布式重构，不在本期 | — |

> 小资金用户实盘可行性依赖 M-1b 选到低门槛（≤10-30 万）券商；若仅找到 50 万门槛券商，小资金档实盘降级为模拟盘。

---

## 2. 需求分析

### 2.1 功能需求（按模块映射）

| 模块 | 核心功能需求 |
|---|---|
| ① 数据层 | 行情订阅/历史、情绪采集（分期）、基础数据、龙虎榜/资金流/自身成交；**PIT 标注（实时/回填区分）**；**交易规则版本表**；**数据质量独立验证层**；**进程内事件总线**；**bar 去重**；**多账户** |
| ② 因子引擎 | 因子注册表、向量化计算、增量截面快照、缓存（DuckDB）、**中性化评价**；**factor_snapshot_id 可复现**；PIT 强制 |
| ③ AI 因子挖掘 | 3a 单 agent → 3b multi-agent；**DSL 手写解释器沙箱**；实验追踪；假设预算 |
| ④ 策略引擎 | Strategy 接口、多策略调度、**组合优化器**、事件驱动模板、**止损止盈/策略生命周期/再平衡频率**、**策略隔离**、**ctx 契约** |
| ⑤ 风控 | 分层：基础（仓位/主板 T+1/涨跌停/申报合法性/**止损止盈**）+ 严肃（回撤熔断/行业暴露/流动性/告警） |
| ⑥ 执行层 | 统一 Broker 接口（per-account）；QMT/模拟适配器；拆单；线程桥接；**on_fill 异步回调** |
| ⑦ 回测引擎 | 事件驱动撮合、摩擦建模、主板 A 股规则、**绩效归因（基准+Shapley+CNE6）**、**实盘-回测一致性校验**、**PIT 置信度打标** |
| ⑧ 情景模拟与复盘 | 反事实回放（**界定边界**）、次日情景（**GARCH/DCC**）、每日复盘 |
| ⑨ 主体行为学习 | Actor 抽象、买卖点样本库（**标签=实现PnL**）、画像、学习→因子（**标准门禁，非两路共识**） |
| ⑩ 可观测性 | 结构化日志、指标落库、告警、三合一复盘报表、**配置热加载**、灰度金丝雀 |
| ⑪ UI / 前端 | Next.js 仪表盘；`DESIGN.md` 作为 UI 设计系统配置源；币安风格深色金融界面、交易语义色、组件 token 映射 |
| ⑫ 前后端 API | 后端 HTTP API（只读优先）+ 前端 API client；替换 mock hooks；统一 loading/error/empty 状态；真实下单 POST 延后到 M4 门禁后 |
| 横切 | 数据质量验证层 · 实验追踪 · PIT 语义 · 盘前盘后流程 · 事件总线 · 密钥管理 |

### 2.2 非功能需求

| 维度 | 要求 |
|---|---|
| 正确性 | 接口层三态共用；PIT 强制（实时段可证 / 回填段标注）；交易规则按生效日期取值；多重假设校正（FDR 分母用预算数）；回测可复现（snapshot_id） |
| 可靠性 | 断线重连、客户端崩溃检测、订单状态机幂等、盘后对账、崩溃可恢复、数据损坏可回滚、**DuckDB 单写进程交接**、**bar 去重** |
| 性能（按作用域） | 单标的纯策略逻辑 < X ms；全市场因子面板计算 Y 秒；两者经流水线并行；**不做毫秒级承诺** |
| 可演进性 | 接口边界清晰，迁移路径存在（**但分布式迁移需重写并发模型与网络边界**，非零成本） |
| 合规 | 情绪/社媒遵守 ToS 与 PIPL；私域爬取默认关闭；见 §16 数据合规清单 |

### 2.3 关键约束与决策汇总

| 维度 | 决策 |
|---|---|
| 系统范围 | 分阶段：M-1a/M-1b 探测 → 模拟盘 → 实盘 |
| 交易通道 | QMT/MiniQMT（xtquant），统一接口（M-1b 验证） |
| 账户 | **单用户多券商账户**（account_id 维度） |
| 策略核心 | 一期：因子挖掘管线 + 市场宽度/资金流因子；二期：散户情绪反向 |
| 情绪数据源 | 分期：① 聚合指标+授权源（北向/两融标"不宜作反向源"）② 社媒爬虫（合规开关默认关） |
| AI 基础 | 商用 API（DeepSeek 主）+ 单 agent 起步 → multi-agent；**DSL 手写解释器沙箱** |
| 资金定位 | 小资金 + 中等规模（档内分档）→ 风控分层 |
| 存储/中间件 | SQLite（事务）+ DuckDB（分析）+ asyncio；零独立中间件 |
| 交易范围 | **当前阶段仅沪深主板股票**；科创/创业/北交/ETF/可转债后续扩展 |
| 交易规则 | TradingRuleProvider 按市场/品种/生效日期返回（独立子模块 M0.5）；当前规则集仅录入沪深主板股票 |
| 结算 | 当前按主板股票 **T+1** 落地；Provider 保留 per-product T+N 扩展口 |
| ⑧ 次日模拟 | **GARCH/EGARCH-t + DCC**，路径过撮合模拟器，AI 融合显式公式 |
| ⑨ 行为学习 | 三者并行（统计+AI归纳+ML），**标准门禁入库**，按 actor 切 OOS |

---

## 3. 总体架构

### 3.1 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│            配置层 (YAML/TOML, 部分热加载)  策略/风控/资金/账户        │
└──────────────────────────────────────────────────────────────────┘
        │                                                           │
┌───────▼────────────┐                                 ┌────────────▼──────────┐
│ ① 数据层 Data      │                                 │ ⑦ 回测引擎 Backtest   │
│  · 行情网关(QMT)   │                                 │  + 绩效归因(Shapley/  │
│  · 情绪采集(分期)  │                                 │    CNE6)              │
│  · 基础/龙虎榜/    │                                 │  + 实盘-回测一致性校验│
│    资金流/自身成交 │                                 │  + PIT置信度打标      │
│  · PIT标注(实时/   │                                 └────────────┬──────────┘
│    回填)           │                                              │
│  · 交易规则版本    │                                              │
│  · bar去重/事件总线│                                              │
│  · 多账户          │                                              │
└───────┬────────────┘                                              │
   事件总线│ publish(BarEvent)                                       │
        ▼                                                           │
┌────────────────┐  ┌──────────────┐  ┌──────────────────────┐     │
│ 数据质量验证层 │→│ ② 因子引擎   │←─│ ③ AI因子挖掘(离线)   │     │
│ (独立,deny-    │  │ 中性化/snap- │  │ 3a单agent→3b多agent  │     │
│  default)      │  │ shot/增量截面│  │ DSL解释器/实验追踪    │     │
└────────────────┘  └──────┬───────┘  └──────────────────────┘     │
                           ▼ 因子值   ┌──────────────────────┐     │
                    ┌──────────────┐  │ ⑨ 主体行为学习      │ 行为 │
                    │ ④ 策略引擎  │←─┤ Actor(标签=PnL)/样本 │ 因子 │
                    │ Strategy/调度│  │ /画像/标准门禁入库   │      │
                    │ +组合优化    │  └──────────┬───────────┘      │
                    │ +止损止盈/   │             │ 行为先验          │
                    │  生命周期/   │             ▼                   │
                    │  再平衡/隔离 │     ┌──────────────────┐        │
                    └──────┬───────┘     │ ⑧ 情景模拟与复盘 │        │
                           ▼             │ GARCH/DCC反事实 │        │
                    ┌──────────────┐     │ /每日复盘        │        │
                    │ ⑤ 风控(分层) │     └────────┬─────────┘        │
                    │ T+1/止损止盈 │              │ 复用回测         │
                    └──────┬───────┘              └──────────────────┘
                           ▼ 目标订单(多账户)
                    ┌──────────────┐
                    │ ⑥ 执行层    │
                    │ Broker/账户  │
                    │ QMT|模拟     │
                    │ on_fill异步  │
                    └──────┬───────┘
                           ▼
        ┌──────────────────────────────────────────────────┐
        │ ⑩ 可观测性: 日志/指标/告警/三合一报表/热加载/灰度    │
        └──────────────────────────────────────────────────┘
   │ 事务表(account_id)         分析表(单写进程交接)
   ▼                            ▼
 SQLite(订单/持仓/审计/配置/    DuckDB(行情/因子物化/tick)
       Actor/experiment)         内存/SQLite WAL→异步append

 并发: 行情线程→asyncio入队→因子/策略 offload ProcessPool→回asyncio→下单
       SQLite写=独立线程; DuckDB=单写进程(盘中/盘后交接)
 横切: 数据质量验证层 · 实验追踪 · PIT语义 · 盘前盘后流程 · 事件总线 · 密钥管理
```

### 3.2 模块清单

① 数据层 · ② 因子引擎 · ③ AI 因子挖掘 · ④ 策略引擎 · ⑤ 风控 · ⑥ 执行层 · ⑦ 回测引擎 · ⑧ 情景模拟与复盘 · ⑨ 主体行为学习 · ⑩ 可观测性 · ⑪ UI / 前端 · ⑫ 前后端 API

（数据质量验证层、组合优化器、绩效归因、实验追踪、PIT 语义、盘前盘后流程、事件总线、密钥管理、UI 设计系统 token、前后端 API 契约作为子模块或横切能力嵌入。）

### 3.3 核心设计原则

1. **接口层三态共用（诚实表述）**：策略/风控/执行接口在回测/模拟/实盘一致，唯一差异是 Broker 适配器；撮合行为不对称需校准 + 实盘落 tick；ctx 持仓新鲜度与 Broker 同步/异步阻抗需显式处理（on_fill 回调模板）。
2. **point-in-time 分级**：实时采集段 PIT 可证；回填段 `available_at` 为规则推断（`pit_confidence=rule_inferred`），回测结果打标，不与实盘段混。
3. **回测可复现**：每次回测绑定 `factor_snapshot_id`（冻结数据快照），区分代码版本（factor_version）与数据快照（snapshot_id）。
4. **交易规则版本化**：当前主板股票的涨跌幅/tick/数量/费用/结算 T+1/时段按市场/生效日期取值，不硬编码，规则表来自官方并留来源；后续品种再扩展 per-product T+N。
5. **分层并发**：行情线程 → asyncio 入队 → 因子/策略 CPU 计算 offload ProcessPool → 回 asyncio → 下单；SQLite 写独立线程；DuckDB 单写进程交接；网关背压。
6. **分期最小必要质量**：每里程碑可运行、可验证（量化阈值+测量脚本）、可回滚。
7. **风控分层**：基础层（小资金）+ 严肃层（中等规模，档内分档参数）。
8. **防过拟合贯穿**：样本外/walk-forward、FDR（分母用预算数）、锁死 holdout（一次性永久锁）、新颖性 0.5-0.7、AI 归纳已知因子百科查重。
9. **抽象先行**：Repository/Provider/Broker/Factor/Strategy 均为接口，**业务语义不暴露存储特性**（性能特性可保留）；分布式迁移需重写并发模型，非零成本。
10. **UI 配置单一来源**：`DESIGN.md` 是前端视觉 token 与组件风格的权威配置源；实现层（Tailwind/theme/components）只做映射，不在页面内散落硬编码颜色、字号和圆角。

---

## 4. 模块详细设计

### 4.1 数据层

**职责**：采集、清洗、存储、提供数据；PIT 标注（实时/回填区分）；交易规则版本；事件总线；bar 去重；多账户适配。

#### 4.1.1 行情网关

- 实时：xtdata 订阅 tick/分钟线；进程内环形缓冲。**实盘 tick 先落内存/SQLite WAL + 异步批量 append DuckDB**（崩溃安全 + 高吞吐，绕开 DuckDB 单写锁；或落 Parquet 盘后注册）。
- **xtquant 线程桥接**：回调在内部线程，固定 `loop.call_soon_threadsafe` 桥接到 asyncio；回测/模拟/实盘共用。
- **事件总线**：网关 `publish(BarEvent)`，因子/可观测/落盘/⑧⑩ 各自订阅，新增消费者不改网关。
- **bar 去重**：bar 带唯一键 `(symbol, freq, trade_ts)`，网关层去重，防断线重连重发触发重复信号。
- **背压**：bar 队列深度超阈值时降频/合并/丢弃 + 告警。
- **客户端崩溃**：xttrader 心跳检测进程存活，崩溃告警 + "只平不开"安全态。
- 断线指数退避重连。

> ⚠ xtquant 已完成 Windows + QMT 登录态下的只读行情/trader 握手探测；本地连续 20 交易日模拟盘对账已通过；订阅频率、真实回调线程、下单/撤单延迟、断线恢复与真实 QMT 回报对账仍待 M4 live 门禁验证。

#### 4.1.2 情绪采集（分期）

- **一期（合规主路径，市场宽度/资金流，非"散户情绪"）**：涨跌停家数/连板高度/封板率（可由行情自算）、融资融券余额变化、东方财富股吧/雪球**匿名化聚合指标**（讨论数、关键词词频，不存可识别个人内容）。
  - **北向资金、融资融券标注"不宜作反向因子源"**：北向是聪明钱（反向=反 alpha），两融是杠杆头寸（机构+散户混合）；仅作趋势/状态因子。
- **二期（合规开关默认关，散户私域情绪反向）**：抖音/小红书/微博热门爬虫，需用户显式知情开启——**这才是参考资料所述"散户情绪反向"alpha 的真正数据源**。

> 一期差异化定位诚实化：一期交付"因子工程管线 + 市场宽度因子"，**不宣称散户情绪反向**；二期才兑现资料核心 alpha。

#### 4.1.3 基础数据与交易规则

基础数据：股票清单、复权因子、交易日历（**含调休，数据源 exchange_calendars + 交易所公告人工 overlay**）、ST/停牌/退市（含退市整理期）、板块归属、指数成分、证券类别、交易权限、**最小报价单位档位**。

交易规则 `TradingRuleProvider`（独立子模块，见 M0.5），按 `market + board + product_type + effective_from/effective_to` 返回。**当前阶段只录入沪深主板股票规则**，接口保留科创/创业/北交/ETF/可转债扩展字段：

- 价格：申报价格最小变动单位（主板股票常规 0.01 元）、涨跌幅比例、无涨跌幅窗口、有效价格申报范围。
- 数量：买入最小数量、递增单位（主板 100 整数倍）、卖出不足一手处理、最大申报数量。
- 结算：当前主板股票 **T+1**；Provider 保留 `settlement` 字段，后续品种再填 per-product T+N。
- 时段：开盘/连续/收盘集合竞价、盘后固定价格交易（预留）。
- 费用：佣金、印花税、过户费、经手费，全部配置化带生效日期。

#### 4.1.4 行为数据（支撑⑨）

龙虎榜（交易所公开）、资金流向/大单（可选 L2）、自身成交（QMT 导出，多账户）；均带 `available_at`（龙虎榜 T 日 18:00 后）。

#### 4.1.5 point-in-time 标注（实时/回填分级）

每外部事实表带 `available_at`、`source`、`ingested_at`，必要时 `published_at`。

| 数据源 | available_at |
|---|---|
| 日线 OHLC（实时段） | T 日 15:00 后（可证） |
| 日线 OHLC（回填段） | 规则推断 `pit_confidence=rule_inferred` |
| tick/分钟 | `received_ts`（实际到达本机，非 event_ts） |
| 龙虎榜 | T 日 18:00 后 |
| 融资融券 | T+1 日公布 |
| 财报 | 报告期 + 披露日 |
| 交易规则 | 官方发布日 + 生效日（决策按生效日取） |

```python
class PointInTimeSeries:
    field: str; value: Any; trade_date: date
    available_at: datetime; source: str; ingested_at: datetime
    pit_confidence: Literal["live", "rule_inferred"]   # 实时可证 / 回填推断
```

因子物化 `available_at` 取依赖字段 `available_at` max 与计算完成时间较晚者。**回填段标记 `pit_confidence=rule_inferred`，回测结果打标 `backtest_on_inferred_pit`，不与实盘段混。**

#### 4.1.6 数据质量验证层（独立，非数据层子模块）

**生产者与把关者分离**：① 数据层只采集 + PIT 标注，不判定是否可用；独立验证层 deny-by-default，拦截脏数据不进因子引擎。

- 缺失率、异常值（跨截面 z-score）、停牌填补、**复权断裂检测**、新上市/退市边界。
- 多源差异率、字段延迟、修订频率、接口失败率；关键源超阈值进隔离区。
- 规则变更需人工确认后入 `trading_rule`；变动触发撮合/风控回归测试（用**人工标注 golden cases**，非规则表自验，避免循环）。
- 失败注入测试由独立于 ① 的角色编写。

#### 4.1.7 接口

```python
class MarketDataGateway(Protocol):
    def subscribe(self, symbols, freq, on_bar): ...
    def history(self, symbol, freq, start, end, as_of=None): ...
    def bar_at(self, symbol, freq, t, decision_time): ...   # PIT 安全

class SentimentProvider(Protocol):
    def sentiment(self, symbol, t) -> float: ...            # 仅聚合指标
    def market_sentiment(self, t) -> MarketSentiment: ...

class TradingRuleProvider(Protocol):
    def rules_for(self, symbol, decision_time, require_verified: bool = False) -> TradingRule | None: ...
    # 当前主板T+1，保留settlement扩展；实盘路径 require_verified=True，provisional/pending 返回 None 以阻断新开仓
```

---

### 4.2 因子引擎

**职责**：因子声明、计算、增量截面、缓存、中性化评价、可复现。

#### 4.2.1 抽象

```python
class Factor(Protocol):
    name: str; factor_version: str
    inputs: list[FieldRef]           # 含 PIT
    def compute(self, ctx: FactorContext) -> pd.Series: ...

class FactorRegistry:
    def compute_panel(self, names, t, universe, snapshot_id) -> pd.DataFrame: ...
```

#### 4.2.2 计算引擎

- 横截面+时序混合；pandas/numpy 向量化，热点 numba；**CPU 计算经 ProcessPool offload**（不阻塞 asyncio）。
- **增量截面快照**：维护 in-memory 当前截面（新 bar 增量更新），横截面算子基于快照算，单 bar 只触发该 symbol 重算非全市场。
- 增量缓存物化 DuckDB，键 `(factor, factor_version, trade_date, symbol, as_of, snapshot_id)`。
- PIT 强制：`FactorContext` 注入 `decision_time`，所有访问经 `PointInTimeSeries` 断言；**因子代码只能通过注入的 ctx 访问数据，禁止直接 import duckdb/sqlite**。
- 因子表达式/参数/依赖/复权方式变更 → 新 `factor_version`；**数据修订 → 新 `as_of`，回测绑定 `snapshot_id`（冻结 as_of 集合）保证可复现**。

#### 4.2.3 因子评价（强制中性化 + 统计严谨）

| 指标 | 定义 |
|---|---|
| IC | **rank IC（Spearman）**，在**行业 + log(市值) 中性化残差**上计算 |
| IR | mean(IC)/std(IC)，**Newey-West 调整 t 统计**（lag ≥ 持仓周期） |
| 分层回测 | 10 分位 + 多空扣费后年化 + 多空换手 |
| 因子衰减 | 非重叠 forward return 的 IC 衰减 |
| 新颖性 | **因子值 Spearman + 收益预测相关双查，任一 > 0.5-0.7 拒绝**；并对**已知因子百科**（Alpha101/GPO/常见风格）查重 |

#### 4.2.4 防过拟合

- walk-forward（选模型，**非真 OOS**）+ **锁死 holdout（真 OOS，一次性永久锁，forward-walking 出新 holdout，删"冷却"措辞）**。
- **多重假设校正**：FDR 分母用**预登记假设预算数**（非实际数，防 optional stopping）；跨三路候选入库前做**族级 BH-FDR**；变体计入 N。
- **双门入库**：统计显著（BH-FDR p<0.05）**且**经济显著（IC ≥ 0.03、IR ≥ 0.5、分层多空扣费后年化 ≥ 阈值）。
- LLM 归纳因子加**已知因子百科查重**，匹配者降级/对照。

---

### 4.3 AI 因子挖掘（单 agent 起步 → multi-agent 渐进）

#### 4.3.1 分期

- **3a 单 agent 假设生成（M3）**：LLM 出假设 + DSL 表达式；严格样本外验证。**命题：LLM 能否稳定产出可检验、有 alpha 的因子假设**——M3 末做命题裁决（go/no-go），0 因子入库 = 命题证伪 → M6 暂缓。
- **3b multi-agent 闭环（M6）**：Hypothesizer → Composer → Tester → Judge → Iterator；状态落 `agent_run` 可恢复。

#### 4.3.2 实验追踪（横切，③⑨共用）

每次记录：研究主题、假设预算、假设、DSL 表达式、参数、LLM 版本快照、seed、样本内外表现、假设检验记录、`snapshot_id`，落 `experiment` 表。**复现性改为"固定模型版本快照 + 测 run-to-run 方差"**（商用 API temperature=0 非比特可复现）。

#### 4.3.3 DSL 算子集 + 手写解释器沙箱（M3 前冻结）

**沙箱选 DSL 路线**：LLM 产算子表达式字符串 → **手写解释器**执行（解释器内部是受信任的 pandas/numpy 代码），PIT 安全/缺失值传播/向量化在解释器层一次性解决。

算子集（参考 WorldQuant Brain）：时序（`delay/ts_mean/ts_std/ts_rank/ts_max/ts_delta/ts_corr/decay_linear`）、横截面（`rank/zscore/quantile/winsorize/scale`）、分组中性化（`group_neutral`）、算术/条件/非线性（`signed_power/sigmoid/tanh/where`）。**算子集 = 沙箱边界**，新增算子需评审。

> 删除 RestrictedPython 作主沙箱（不能表达 pandas 向量化链式调用）。若 3b 需 LLM 产 Python 源码，改子进程 + seccomp/nsjail + 硬超时。

#### 4.3.4 技术选型与密钥

- LLM：DeepSeek（国内直连、便宜、推理强）为主；Claude/GPT 可选（需代理）。
- 自研轻量调度（函数调用 + 状态机），状态落库。
- **密钥管理**：`keyring` 库 + 按环境分 namespace（`trade-research`/`trade-simulation`/`trade-production`）；Linux 无桌面 fallback 加密文件（age/gpg）；**环境互斥锁**防研究脚本误连实盘；**MiniQMT 认证是客户端登录态非 API key**，密钥管理只覆盖 LLM API key + 数据源 token。

---

### 4.4 策略引擎

**职责**：Strategy 接口、多策略调度、组合优化、止损止盈、策略生命周期、再平衡、ctx 装配、策略隔离。

#### 4.4.1 策略接口与 ctx 契约

```python
class Strategy(Protocol):
    name: str; required_factors: list[str]
    def on_bar(self, ctx: BarContext) -> list[Signal]: ...
    def on_fill(self, ctx: FillContext) -> None: ...        # 三态统一异步入口
# Signal(symbol, direction, strength, target_weight, stop_loss, take_profit, trailing, reason)

class BarContext:           # 由 StrategyRunner 装配
    bar: Bar; decision_time: datetime; clock: Clock
    account_id: str; account: Account; positions: PositionView   # positions 带 as_of/confidence
    factor_panel: pd.DataFrame; rules: TradingRule; trace_id: str

class StrategyRunner:
    def run(self, strategies, account_id, clock): ...   # 按 required_factors 预计算装配 ctx
```

#### 4.4.2 多策略调度 + 策略隔离

- 并行执行；冲突按权重/投票/强度裁决；资金按风险预算切分。
- **策略隔离**：每策略 `on_bar` 包 try/except + 超时（asyncio.wait_for 对协程，子进程对 CPU-bound）；单策略异常不阻断整 bar。
- **目标持仓差分下单**：策略输出目标持仓，执行层做差分，抗重复 bar。

#### 4.4.3 组合优化器（带约束最优化）

明确**标量化目标**：`max α'w − λ·TE² − γ·turnover`，λ（风险厌恶）/γ（换手惩罚）设定方法文档化（效用函数/风险预算/历史回测调参——**λ/γ 调参计入假设数**）。**基准可配置**（默认 CSI500 或自定义）。

- 约束：单票上限、行业暴露、换手率（**惩罚项为主，硬约束作上限**，避免信号翻转大时 QP 不可行）、**主板 100 股 lot 整数化**（后续品种再扩展多 lot 变量）、最小持仓。
- 求解：QP（cvxpy）连续解 → round + 约束修复启发式（按 alpha 强度降序贪心填充，违反约束降一档 lot 重试，超时回退连续解）；**强制报告 QP 解 vs 整数化后目标 gap，gap > 阈值告警**。
- 求解器：盘中 QP+round（开源 OSQP）；盘后允许 MIQP（SCIP via pyscipopt），超时兜底；中等规模 B 可接 Gurobi。

#### 4.4.4 止损止盈 / 策略生命周期 / 再平衡

- **止损止盈**：Signal 带 `stop_loss/take_profit/trailing`；风控基础层每 bar 检查触发（持仓级，区别于组合级回撤熔断）。
- **策略生命周期**：状态机 `draft → backtested → paper → approved → live → monitoring → degraded → offline`；上线门禁（回测指标达标 + 人审，单用户人审=自审独立性有限，以规则化门禁为主）；在线监控 IC/换手/回撤，衰减到阈值自动降级/下线。
- **再平衡频率**：触发模式可配置（定时日频/周频、事件驱动、漂移超阈值 drift>X%）；不同频率换手差异在 M1.5 验证。
- **事件驱动策略模板**：节点识别 → 快速组装 → 短期回测 → 影子验证 → 自动下线（生效窗口/最大亏损/最大持仓天数/到期下线）。

---

### 4.5 风控（分层）

| 层 | 适用 | 规则 |
|---|---|---|
| 基础层 | 全档启用 | 单票/总仓位上限、**主板 T+1 结算约束（从 rules.settlement 取）**、涨跌停/停牌/ST/退市过滤、申报价格 tick/数量合法性、交易权限、**单仓位止损/止盈/跟踪止损**、单笔金额上限 |
| 严肃层 | 中等规模（档内分档参数） | 最大回撤熔断、行业/风格暴露、流动性占比、隔夜系统性风险开关、实时监控告警 |

> 风控基础层是回测撮合一部分，M1 即需就位。所有规则从 `TradingRuleProvider` 读取。组合优化器做连续解整数化，**风控做整数化后合法性最终校验**（避免双重修复不一致）。

```python
class RiskEngine:
    def check(self, orders, account_id, market) -> RiskResult: ...   # 含止损止盈检查
```

熔断：审计 + 告警 + 降仓/"只平不开"，人工解锁。

---

### 4.6 执行层（多账户）

**职责**：统一 Broker 接口（per-account），对接 QMT/模拟；拆单；线程桥接；on_fill 异步回调。

#### 4.6.1 统一接口（per-account）

```python
class Broker(Protocol):
    def place(self, order, client_order_id) -> str: ...
    def cancel(self, order_id) -> None: ...
    def status(self, order_id) -> OrderStatus: ...
    def positions(self) -> list[Position]: ...
    def account(self) -> Account: ...
    is_synchronous: bool   # SimBroker=True, QmtBroker=False

class QmtBroker(Broker): ...   # per-account 实例
class SimBroker(Broker): ...
```

#### 4.6.2 订单状态机 + on_fill

`PENDING → SUBMITTED → PARTIAL_FILLED → FILLED`（或 `CANCELLED/REJECTED`），幂等可恢复。`client_order_id` 本地唯一约束防断线重复下单。状态回报与轮询写 `order_event`，本地订单簿由事件重放恢复。**提供 `on_fill` 异步回调作为三态统一成交入口**（禁用"同 bar 内查 status 决策"反模式，规避 SimBroker 同步 vs QmtBroker 异步阻抗）。

#### 4.6.3 拆单（中等规模）

TWAP/VWAP，按成交额与盘口深度自适应分片（零售通道有效性 M-1b 实测）。

#### 4.6.4 对账

每日盘后用 Broker 查询结果对账本地订单簿，差异落审计告警。

---

### 4.7 回测引擎

**职责**：事件驱动撮合，摩擦建模，绩效归因，一致性校验，PIT 打标。

#### 4.7.1 撮合模型

- 事件驱动 Bar/Tick，与实盘 on_bar 同路径。
- 限价按盘口/成交量分布；市价按次日开盘或当前 bar+滑点；**无 L2 时保守成交概率模型，结果标 `bar_level_simulated`**，不与盘口级实盘复盘混。
- **一字板封死 = 无法成交**；成交不超当日量比例；申报价格/数量合法性；收盘集合竞价撮合；规则从 `TradingRuleProvider` 按当日生效版取。

#### 4.7.2 交易摩擦

佣金（券商配置/成交回报/盘后对账）、印花税（卖方 0.05%，**配置化以最新政策为准**）、过户费（当前主板公共费率已 source-audit verified，按市场/品种/生效日配置）、经手费（当前主板公共费率已 source-audit verified）、滑点（成交额/波动率建模）。

#### 4.7.3 A 股规则

当前阶段按沪深主板股票规则落地：T+1、主板/风险警示/新股窗口涨跌幅、停牌跳过、100 股整数倍申报、集合竞价时点、0.01 元价格 tick、交易权限。科创/创业/北交/ETF/可转债进入扩展范围前，必须先补规则 fixture 与 source_confidence。

#### 4.7.4 绩效归因子系统

- **基准可配置**（默认 CSI500/自定义）。
- **多策略相关因子用 Shapley 归因或正交化回归归因**（避免共线下顺序 Brinson 病态）；因子贡献分解。
- **Barra 命名 CNE6**，自校准或简化风格因子（规模/价值/动量/波动）起步（机构级全 Barra 对个人偏重，YAGNI 标注）。

#### 4.7.5 实盘-回测一致性校验

M4 实盘 1 月后，同段实盘行情灌回回测引擎（**重放至实盘当时 snapshot_id**，否则偏差含 PIT 选择差异不可比），对比成交价/概率/滑点偏差，校准摩擦模型。

#### 4.7.6 正确性自检

- 防 look-ahead：PIT 强制 + 运行时锚 + **因子代码强制经 ctx**（禁直接读库）。
- 复权：量价因子默认不复权 + corporate action 显式调整；展示/收益曲线可前复权；用前复权须在因子元数据标注。
- **回填段打标 `backtest_on_inferred_pit`**。

---

### 4.8 情景模拟与复盘引擎（⑧）

#### 4.8.1 反事实回放（界定边界）

基于 event-sourced 历史 tick/bar 重放，改写决策观察差异，复用 ⑦ 撮合。**边界声明**：仅对**自身小单扰动**保证撮合一致性；**actor 移除/大单移除需价格冲击模型**（Almgren-Chriss 或经验冲击函数），否则降级为"相关性叙事"非因果。

#### 4.8.2 次日情景生成（GARCH/DCC + 过撮合）

- **方向先验**：当日收盘因子/情绪/龙虎榜/行为特征（PIT 安全）→ 次日收益方向先验。
- **蒙特卡洛**：**GARCH/EGARCH-t（波动聚集+肥尾）+ DCC（动态相关，危机态相关→1）**生成 N 条路径；**校准**（EWMA λ=0.94 或 60d/250d 双窗口对比、跳跃强度估计、N 收敛判据 1%/5% 分位稳定）。
- **路径强制过撮合模拟器**：涨跌停截断/T+1/集合竞价在路径评估层生效，而非塞进价格过程。
- **AI 预测融合显式公式**：`μ_adjusted = μ_factor + κ·(p_up_ml − 0.5)`，去相关因子信号防双重计数。
- 用途：多情景稳健性（VaR/条件回撤/最差情景），**VaR 95%/99% 回测覆盖率达标**（阈值 M5a 定义）。

#### 4.8.3 每日复盘报告

信号表现、实际 vs 预期偏差归因、买卖点质量评分、情绪/资金/龙虎榜事件回放；自动归档。

---

### 4.9 主体行为学习层（⑨）

**职责**：游资/自己/北向/机构等行为主体买卖点学习 → 策略迭代。

#### 4.9.1 Actor 抽象

```python
class Actor:
    id: str; kind: ActorKind   # SELF / HOT_MONEY / NORTHBOUND / INSTITUTION
    def trades(self, start, end) -> list[ActorTrade]: ...
# ActorTrade(symbol, time, side, price, volume, realized_pnl, context)
```

#### 4.9.2 数据来源（带偏差声明）

游资（龙虎榜席位，**仅上榜股样本，标"仅适用于高波动/高换手子集"**，回测在对应子集做，不做全市场外推）、北向（沪深股通）、自己（QMT 导出，多账户，小样本降级为审计）、机构（可扩展）。

#### 4.9.3 三路并行学习（标签修正 + 删两路共识）

| 路径 | 方法 | 产出 |
|---|---|---|
| 统计画像 | 胜率/盈亏比/持仓周期/板块偏好/买卖点特征 | 可解释画像 + 启发式规则 |
| AI 归纳 | Agent 读样本归纳高胜率条件（喂 ③，已知因子查重） | 候选因子/规则 |
| ML 模仿 | **标签 = actor 实现 PnL**（非"是否盈利"，防前视）；特征 PIT 约束；**按 actor 切 OOS**（某 actor 训练则该 actor 全期 OOS，不按时间切） | 候选打分因子 |

#### 4.9.4 入库门禁（标准门禁，非"两路共识"）

**删除"两路共识即入库"逻辑**（三路同源数据非独立样本，共识仅作鲁棒性证据）。入库仍走标准门禁：样本外 + BH-FDR + 新颖性 + 经济显著性 + 人审。方法间一致性作为鲁棒性必要非充分。

#### 4.9.5 自身画像降级

小样本统计无意义，降级为"交易行为审计 + 规则化提醒"（追高/割肉/持仓过久），非建模对象。

---

### 4.10 可观测性

- 结构化 JSON 日志，trace_id 全链路。
- 指标落 SQLite（多账户维度）。
- 告警（企业微信/邮件/Server酱）。
- **三合一复盘报表**：价格+成交量+情绪+关键时点信号标注；生产 UI 走 Next.js 仪表盘，研究/离线可用 notebook/Plotly 辅助。
- **配置热加载**：风控阈值/资金参数/因子权重支持盘中热加载（文件 watch + 校验生效）。
- **灰度金丝雀**：新策略影子→小仓位→达标放量（成熟度档位→动态资金分配）。

### 4.11 UI / 前端设计系统

**职责**：为复盘、监控、交易终端、研究回测四类界面提供一致的金融平台 UI。前端以 `DESIGN.md` 为视觉配置源，落地到 Tailwind theme、基础组件与页面布局。

#### 4.11.1 设计系统配置源

- `DESIGN.md` 是 UI token 的权威来源，包含 `colors`、`typography`、`rounded`、`spacing`、`components` 与使用说明。
- 前端实现只消费/映射这些 token：例如 Tailwind 颜色、字号、圆角、间距、按钮/表格/卡片组件；不得在业务页面随意新增近似色或一次性样式。
- 若视觉策略调整，先改 `DESIGN.md`，再同步 theme/components；设计文档只记录约束，不复制完整 token 表。

#### 4.11.2 视觉原则

- 风格：深色金融交易平台，主画布 `canvas-dark`（#0b0e11），卡片 `surface-card-dark`（#1e2329），少量浅色交易表单/弹窗按 `canvas-light` 系列处理。
- 品牌/强调色：`primary`（#FCD535）只用于主 CTA、关键状态、链接和高优先级强调；禁用状态使用 `primary-disabled`。
- 交易语义：上涨/盈利/买入倾向使用 `trading-up`（#0ecb81），下跌/亏损/卖出倾向使用 `trading-down`（#f6465d）；价格方向优先用文字/数字颜色表达，避免把涨跌做成大面积背景。
- 字体：优先使用 `DESIGN.md` 的 BinanceNova/BinancePlex 语义；实际开源替代为 Inter（正文/标题）+ IBM Plex Sans 或等价数字字体（价格、收益率、成交量）。
- 形态：按钮 6px、输入/普通卡片 8px、主要容器 12px；仪表盘避免大圆角和装饰性渐变。
- 密度：交易/监控界面保持紧凑、可扫描；复盘/研究页面允许图表区更宽，但仍使用同一间距标尺。

#### 4.11.3 页面与组件映射

| 页面 | 目标 | 主要组件 / token |
|---|---|---|
| `/monitor` | 盘中监控与告警 | `top-nav-dark`、`markets-table-card`、`price-up-cell`/`price-down-cell`、风险进度与告警色 |
| `/trade` | 模拟/实盘交易终端 | `button-trading-up`、`button-trading-down`、`text-input-on-light`、订单/成交状态色 |
| `/replay` | 三合一复盘 | 深色图表容器、价格/成交量/情绪曲线、信号关键点标注 |
| `/research` | 因子评估与回测研究 | 指标卡、IC/IR/分层收益图、回撤与归因图 |

#### 4.11.4 验收标准

- 页面引用 theme token，不出现未登记的核心色值（少量图表库自动色除外）。
- 组件测试覆盖基础视觉语义：涨跌颜色、按钮状态、交易输入边界、表格状态。
- Next build 与前端测试通过；核心路由 `/monitor`、`/trade`、`/replay`、`/research` 可静态构建。
- UI 不承诺营销页；首屏优先服务可操作仪表盘。

### 4.12 前后端 API 层

**职责**：把后端 `quant/` 领域能力暴露给 Next.js 前端。API 层只做协议转换、鉴权/环境门禁、错误映射与审计，不重写领域逻辑。

#### 4.12.1 分期原则

- **只读优先（M2.5）**：先打通行情/K线、账户、持仓、委托、成交、风险、告警、因子评价、回测结果、策略生命周期。
- **下单延后（M4）**：真实下单 POST 必须等 live gate、kill switch、verified 规则、QMT/M2 模拟盘验收通过后才开放；M2.5 阶段 `/trade` 仍可保留模拟提示。
- **契约单一来源**：响应字段与 `web/src/types/*` 对齐；后端 schema 变更必须带前端类型/测试同步。
- **mock 降级**：`web/src/lib/mock/*` 只保留为测试 fixture 或显式 dev fallback，生产路径默认走 API client。

#### 4.12.2 只读接口集合

| 路由 | 用途 | 前端页面 |
|---|---|---|
| `GET /api/markets` | 主板 universe 行情表 | `/monitor`、首页 |
| `GET /api/kline?symbol=&freq=&start=&end=` | K 线/成交量 | `/replay`、`/trade` |
| `GET /api/account` | 多账户快照 | `/monitor`、`/trade` |
| `GET /api/positions` | 持仓 | `/monitor`、`/trade` |
| `GET /api/orders` / `GET /api/fills` | 委托/成交 | `/trade` |
| `GET /api/risk` / `GET /api/alerts` | 风控状态/告警 | `/monitor` |
| `GET /api/factor-eval` | 因子评价 | `/research` |
| `GET /api/backtest` | 回测结果 | `/research` |
| `GET /api/strategy-lifecycle` | 策略生命周期 | `/research`、`/monitor` |

#### 4.12.3 API 验收标准

- 后端 API 测试覆盖 200 响应、字段结构、错误响应、主板范围约束。
- 前端 hooks 不再直接 import `web/src/lib/mock/*`；统一经 `web/src/lib/api/*`。
- 四个核心路由在本地 API 启动后可展示后端返回数据，并有 loading/error/empty 状态。
- 后端 `.venv/bin/pytest tests/quant -m "not network" -q`、前端 `npm test -- --run`、`npm run build` 通过后，才可声明前后端已对接。

---

## 5. 关键接口契约汇总

| 接口 | 关键方法 | 实现可替换点 |
|---|---|---|
| `MarketDataGateway` | subscribe/history/bar_at(PIT)/publish(BarEvent) | QMT/Tushare/AkShare |
| `SentimentProvider` | sentiment/market_sentiment | 聚合指标/授权源/社媒(开关) |
| `TradingRuleProvider` | rules_for(symbol, decision_time, require_verified) 含 settlement | 官方规则表(独立子模块) |
| `DataQualityGate` | validate(dataset, record) → deny/pass | 独立验证层 |
| `Factor`/`FactorRegistry` | compute/compute_panel(snapshot_id) | 因子后端 |
| `Strategy`/`StrategyRunner` | on_bar/on_fill/run(account_id) | 各策略 |
| `BarContext`/`FactorContext` | (见 §4.4.1 契约) | StrategyRunner 装配 |
| `Clock` | now()/advance() | 三态时间统一 |
| `PortfolioOptimizer` | optimize(signals, constraints, benchmark) | cvxpy/MIP |
| `RiskRule`/`RiskEngine` | apply/check(account_id) | 风控规则集(分层) |
| `Broker` | place/cancel/status/positions/on_fill/is_synchronous | QmtBroker/SimBroker (per-account) |
| `Actor`/`ActorTrade` | trades | 游资/自己/北向 |
| `ScenarioGenerator` | next_day_paths(GARCH/DCC) | 蒙特卡洛+AI |
| `Attribution` | shapley/barra(CNE6) | 归因后端 |
| `ExperimentTracker` | log(run, snapshot_id) | SQLite/MLflow |
| `SecretManager` | get(key, env) | keyring/age |
| `FrontendApi` | read-only REST endpoints + error contract | FastAPI/ASGI → Next.js API client |

---

## 6. 数据模型（SQLite + DuckDB 分工，多账户 + snapshot_id）

> **SQLite（WAL）**：事务表（含 `account_id`）。**DuckDB**：分析表（行情/因子/tick）。**接口不暴露存储业务语义**。

**SQLite（事务）关键表**：

```sql
CREATE TABLE account (account_id TEXT PRIMARY KEY, broker TEXT, env TEXT, name TEXT);
CREATE TABLE orders (order_id TEXT PRIMARY KEY, account_id TEXT, strategy TEXT, symbol TEXT, side TEXT,
    qty REAL, price REAL, status TEXT, broker TEXT, client_order_id TEXT, rule_version TEXT,
    stop_loss REAL, take_profit REAL, created_ts INTEGER, updated_ts INTEGER, reason TEXT,
    UNIQUE(account_id, client_order_id));
CREATE TABLE order_event (event_id TEXT PRIMARY KEY, order_id TEXT, broker_order_id TEXT,
    event_type TEXT, payload TEXT, ts INTEGER);
CREATE TABLE fills (fill_id TEXT PRIMARY KEY, account_id TEXT, order_id TEXT, symbol TEXT, price REAL,
    qty REAL, fee REAL, tax REAL, transfer_fee REAL, ts INTEGER);
CREATE TABLE position (account_id TEXT, symbol TEXT, qty REAL, avg_cost REAL, frozen_qty REAL,
    updated_ts INTEGER, PRIMARY KEY (account_id, symbol));
CREATE TABLE audit_event (id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, ref_id TEXT, account_id TEXT, payload TEXT);
CREATE TABLE actor_trade (actor_id TEXT, symbol TEXT, ts INTEGER, side TEXT, price REAL,
    qty REAL, realized_pnl REAL, context TEXT, PRIMARY KEY (actor_id, symbol, ts, side));
CREATE TABLE experiment (run_id TEXT PRIMARY KEY, kind TEXT, hypothesis TEXT, expr TEXT, params TEXT,
    hypothesis_budget_max INTEGER, n_tests_actual INTEGER, llm_model TEXT, seed INTEGER,
    snapshot_id TEXT, oos_ic REAL, ts INTEGER);
CREATE TABLE agent_run (run_id TEXT PRIMARY KEY, phase TEXT, status TEXT, state TEXT, ts INTEGER);
CREATE TABLE job_run (job_id TEXT PRIMARY KEY, kind TEXT, status TEXT, payload TEXT, ts INTEGER);
CREATE TABLE trading_rule (rule_id TEXT PRIMARY KEY, market TEXT, board TEXT, product_type TEXT,
    effective_from DATE, effective_to DATE, source_url TEXT, source_confidence TEXT,   -- verified/pending/provisional
    rule_json TEXT, reviewed_by TEXT, reviewed_ts INTEGER);
-- effective 区间不重叠由应用层 check_no_overlap + loader 测试保证；SQLite CHECK 不能表达跨行约束。
CREATE TABLE strategy_lifecycle (strategy TEXT PRIMARY KEY, status TEXT, approved_by TEXT,
    approved_ts INTEGER, monitoring_metrics TEXT, degraded_reason TEXT);
CREATE TABLE source_audit (id INTEGER PRIMARY KEY, source TEXT, dataset TEXT, status TEXT,
    diff_rate REAL, latency_seconds REAL, checked_ts INTEGER, detail TEXT);
```

**DuckDB（分析）关键表**：

```sql
CREATE TABLE instrument (symbol VARCHAR, market VARCHAR, board VARCHAR, product_type VARCHAR,
    list_date DATE, delist_date DATE, status VARCHAR, source VARCHAR, available_at BIGINT, ingested_at BIGINT);
CREATE TABLE bar (symbol VARCHAR, freq VARCHAR, trade_date DATE, ts BIGINT,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE,
    adj_type VARCHAR, source VARCHAR, available_at BIGINT, received_ts BIGINT, ingested_at BIGINT, as_of BIGINT,
    pit_confidence VARCHAR);   -- live / rule_inferred
CREATE TABLE factor_value (factor VARCHAR, factor_version VARCHAR, trade_date DATE, symbol VARCHAR,
    value DOUBLE, available_at BIGINT, computed_at BIGINT, as_of BIGINT, snapshot_id VARCHAR, experiment_run_id VARCHAR);
-- tick: 内存/SQLite WAL → 异步批量 append
CREATE TABLE tick (symbol VARCHAR, event_ts BIGINT, received_ts BIGINT, price DOUBLE, volume DOUBLE);
CREATE TABLE pit_field (field VARCHAR PRIMARY KEY, source VARCHAR, available_at_rule VARCHAR);
CREATE TABLE factor_snapshot (snapshot_id VARCHAR PRIMARY KEY, created_ts BIGINT, as_of_cap BIGINT, note VARCHAR);
CREATE TABLE data_snapshot (snapshot_id VARCHAR, dataset VARCHAR, source VARCHAR,
    as_of_cap BIGINT, row_count BIGINT, checksum VARCHAR, PRIMARY KEY(snapshot_id, dataset));
```

**写并发策略**：
- **SQLite**：所有写经**独立写线程**（`threading.Thread` + `queue.Queue`，与 asyncio 解耦，asyncio 侧 `put_nowait` 非阻塞），跨进程写经单写服务进程或 WAL + 写权持有者协调。
- **DuckDB**：**单写进程**（盘中进程独占，盘后交接，见 §9）；写以 append 批量为主。
- **tick**：内存环形缓冲 + SQLite WAL（高吞吐崩溃安全）→ 异步批量 append DuckDB，或直接 Parquet 按日分文件。

---

## 7. 数据流与时序

### 7.1 实盘 / 模拟主线（分层并发 + 事件总线）

```
行情线程(QMT) ─call_soon_threadsafe─► asyncio 入队(去重/背压)
      ──► [事件总线 publish(BarEvent)]
      ──► 因子计算(ProcessPool offload, PIT, 增量截面) ──► 回 asyncio
      ──► 策略 on_bar(BarContext, account_id)(信号+止损止盈)
      ──► 信号仲裁 ──► 组合优化(主板100股整数化) ──► 风控 check(T+1,止损止盈)
      ──► Broker(QMT/模拟, per-account, on_fill异步) ──► 成交回写(独立写线程)
      ──► 持仓/审计 ──► 指标/复盘   (tick 同步落 WAL→DuckDB)
```

### 7.2 回测（snapshot_id 可复现 + PIT 打标）

```
历史数据(DuckDB, PIT) + 规则版本表 + factor_snapshot_id ──► 因子引擎(历史,PIT) ──► 策略
      ──► 组合优化 ──► 风控 ──► SimBroker(撮合,摩擦) ──► 绩效归因(Shapley/CNE6)
      [回填段结果打标 backtest_on_inferred_pit]
```

### 7.3 AI 因子挖掘（离线，命题裁决）

```
因子库+历史(snapshot) ──► [3a] 单agent假设 ──► DSL解释器 ──► Tester(样本外+BH-FDR+新颖性+百科查重+经济显著)
      ──► Judge ──► 入库/归档 ──► [M3 命题裁决 go/no-go] ──► [3b] multi-agent(M6)
```

### 7.4 情景模拟与每日复盘

```
盘后: 收盘状态(因子/情绪/龙虎榜/Actor, PIT, snapshot) ──► 次日情景(GARCH/DCC, N路径) ──► 过撮合模拟器 ──► 稳健性(VaR)
当日: 反事实回放(自身小单) ──► 复盘报告 ──► 归档
```

### 7.5 主体行为学习

```
龙虎榜/北向/自身成交 ──► Actor样本(标签=实现PnL) ──► 三路并行(统计/AI归纳/ML,按actor切OOS)
      ──► 标准门禁(BH-FDR+新颖性+经济显著+人审) ──► 入因子库 ──► 策略
```

---

## 8. A 股特性处理清单（分级）

| 特性 | 实现层 | 处理 |
|---|---|---|
| 交易规则版本 | 数据层+风控+撮合 | `trading_rule` 按 effective 区间生效；人工 golden cases 回归 |
| **结算 T+N** | 风控+撮合 | 当前主板股票 T+1，从 rules.settlement 取；per-product 扩展口保留 |
| 涨跌幅 | 撮合+风控 | 当前主板/风险警示/新股窗口按规则表分支；创业/科创/北交后续补 |
| 新股无涨跌幅窗口 | 撮合+风控 | 沪深主板注册制前 5 日；按上市日计算 |
| 一字板封单 | 撮合 | 封死 = 无法成交 |
| 集合竞价 | 撮合 | 9:15-9:25 开盘、14:57-15:00 收盘；不可撤单窗口按规则表 |
| 申报价格最小变动单位 | 撮合+风控 | 当前主板股票 0.01 元；ETF/基金/可转债后续另表 |
| 申报数量规则 | 组合优化+风控 | 当前主板 100 股整数倍；科创/北交等后续扩展 |
| 停牌/ST/退市（含整理期） | 基础数据+风控 | 标志+剔除 |
| 除权除息扭曲 | 因子层 | 量价因子默认不复权+corporate action 调整；前复权须标注元数据 |
| 过户费 | 撮合 | 当前主板公共费率已 source-audit verified，按市场/品种/生效日配置 |
| 印花税（卖方 0.05%，配置化） | 撮合 | 当前主板公共费率已 source-audit verified，仍以最新政策为准 |
| 经手费 | 撮合 | 当前主板公共费率已 source-audit verified |
| 佣金（配置化） | 撮合 | 券商配置/成交回报/盘后对账，非公开固定规则 |
| 板块准入 | 风控 | 资格+风险准入 |
| 盘后固定价格交易 | 调度+Broker | 预留，首期不用 |
| 节假日调休 | 交易日历+调度 | exchange_calendars + 公告 overlay |

---

## 9. 错误处理与容错

| 场景 | 处理 |
|---|---|
| 行情断线 | 心跳+指数退避重连；"只平不开" |
| xtquant 客户端崩溃 | 进程心跳；告警+安全态；重启重连 |
| 下单失败/超时 | 状态机幂等；重试上限；超时查询兜底 |
| 撮合与本地不一致 | 盘后对账，差异告警+人工 |
| 进程崩溃 | 订单/持仓/agent_run/job_run 全落库；重启恢复 |
| 因子计算异常 | 单因子隔离；ProcessPool 不阻塞主循环 |
| Agent 非法因子 | DSL 解释器拦截；丢弃记录 |
| 风控熔断 | 审计+告警+降仓/停机，人工解锁 |
| SQLite 写锁 | 独立写线程串行化；跨进程单写服务 |
| **DuckDB 单写进程交接** | 盘中进程交易日所有事件结束+落盘完成后关闭写连接，盘后进程开启（文件锁/哨兵协调） |
| bar 重发 | 网关层 (symbol,freq,trade_ts) 去重 |
| job 漏执行 | 幂等+落 job_run+重启扫未完成重跑 |
| 数据损坏/误覆盖 | 每日快照备份+批量 dry-run+可回滚 |
| 规则过期/未确认 | source_confidence 非 verified 禁止实盘新开仓 |
| 数据源漂移 | source_audit 记录；关键字段漂移降级（只复盘不下单） |

**盘前盘后流程（交易日生命周期）**：

- 盘前（9:10）：交易日历校验（调休）→ 规则版本检查（source_confidence）→ 数据更新 → 质量门禁 → 持仓/账户对账 → 就绪检查。
- 盘中：事件驱动（asyncio，QMT 回调→事件总线）→ 监控告警。
- 盘后（17:00）：**DuckDB 写权交接** → 清算对账 → 因子批量计算（DuckDB）→ 复盘报告 → 备份。

**调度（移除 APScheduler）**：盘中纯 asyncio（QMT 回调驱动）；盘后批处理独立进程（**cron/systemd timer + 交易日历校验 wrapper**：`if not is_trading_day(today): exit`）；交易日历驱动器是 master。**每年 11 月国务院公布次年假期后升级 exchange_calendars 并跑日历回归测试**。

---

## 10. 测试策略

| 层级 | 方法 |
|---|---|
| 单元 | 因子计算（含中性化）、风控规则、订单状态机、撮合器、组合优化器、DSL 解释器 |
| 防过拟合 | walk-forward、**BH-FDR（分母=预算数）**、**锁死 holdout（一次性永久锁）**、新颖性 0.5-0.7、已知因子百科查重 |
| PIT/look-ahead | **运行时锚**（available_at ≤ decision_time）+ 静态 AST 扫描 + **因子代码强制经 ctx**（禁直接读库） |
| 交易规则验证 | 当前沪深主板股票 tick/数量/涨跌幅/费用/结算 T+1 fixture（人工 golden cases）；其他板块/品种进入扩展前补 fixture |
| 回测可复现 | 同 snapshot_id 两次运行结果一致；回填段打标验证 |
| 回测验证 | 已知历史事件符合预期；撮合现实性；bar 级与盘口级分开标记 |
| 模拟盘验证 | QMT 模拟 ≥ 1 月，对比回测预期 |
| 影子模式 | 实盘行情驱动，仅建议不下单 |
| 对账测试 | 模拟/实盘成交与本地订单簿一致性（多账户） |
| 挖掘确定性 | 固定模型版本快照 + 测 run-to-run 方差（非比特复现） |
| 情景校准 | GARCH/DCC 参数估计 + VaR 95%/99% 回测覆盖率 |
| 质量门禁 | 独立角色编写失败注入测试 |

**测量脚本契约**（里程碑验收）：对账差异 = `abs(本地持仓金额 − broker 持仓金额)/max(总资产,1元)`；BH-FDR p 取分层收益 t 检验，N 每次 Judge 快照单调累加；连续 20 交易日按 `exchange_calendars` 交易日序连续容忍 0 天中断。

---

## 11. 分期路线图（验证标准量化 + 测量脚本）

| 里程碑 | 内容 | 量化验证标准 |
|---|---|---|
| **M-1a 本地快速探测（1-3 天，go/no-go）** | DuckDB 横截面查询延迟（全市场×200 因子×N 天）；SQLite 单写队列吞吐；exchange_calendars 调休覆盖；**DSL 解释器能否跑通 rolling+rank+group_neutral 真实因子**；免费数据源字段完整性+PIT 可推导性；中文金融情绪模型（Chinese-FinBERT）效果 | 全本地无外部依赖；性能/字段/DSL 三项达标 → go |
| **M-1b 外部通道探测（数周，并行）** | xtquant 开户（低门槛券商优先）、订阅频率、回调线程、下单延迟、客户端崩溃恢复、拆单成交质量 | 可开户/订阅所需频率/下单延迟<阈值 → go；否则换通道 |
| **M0 基础设施** | 骨架、配置（部分热加载）、SQLite+DuckDB+Repository（多账户）、ProviderRegistry、事件总线、日志/指标、日历（调休）、基础数据、PIT 字段+事实字段、`trading_rule`、数据质量独立验证层、UI theme 从 `DESIGN.md` 映射 | 读写+PIT 断言+规则按日取值+质量门禁拦截+多账户隔离；单测通过；前端 theme/components 测试通过 |
| **M0.5 交易规则子模块** | 规则表 v1 录入（沪深主板股票，2020 至今）+ **人工 golden cases 标注** + 三方校对 + 区间查询正确性 + source_confidence 体系；科创/创业/北交/ETF/可转债列为后续扩展 | 主板 fixture 100% 通过；区间查询无重叠命中；已审计公共费率 verified；未知或新增 provisional 项继续阻断实盘 |
| **M1 回测+因子+基础风控** | 因子引擎（中性化评价）+ 基础因子、回测引擎（撮合/摩擦/主板 A 股规则/一字板/T+1）、风控基础层、PIT 强制、snapshot 可复现、绩效归因（Shapley 简化版） | 工程正确性：主板规则 fixture 100%、look-ahead 0 报警、已知历史事件回放符合预期、同 snapshot 二次运行一致、连续 3 年（2020+）无异常；基准绩效仅 sanity check（不劣于同 universe buy-and-hold -X%） |
| **M1.5 策略引擎** | Strategy/on_fill、多策略调度+隔离、组合优化器（主板 100 股整数化+gap 度量）、止损止盈、策略生命周期、再平衡、事件驱动模板、ctx 契约 | 多策略并行回测；优化约束满足；QP-vs-整数化 gap < 阈值；换手 ≤ 配置上限；生命周期状态机可迁移 |
| **M2 模拟盘主线（多账户）** | 行情网关（线程桥接+事件总线+背压+去重）、Broker（SimBroker+QmtBroker per-account）、on_fill、xtquant 崩溃处理、DuckDB 写权交接、每日对账 | QMT 模拟**连续 20 交易日**（按日历，容忍 0 中断）跑通信号→下单→持仓→对账闭环；对账差异 < 0.1%；多账户隔离正确 |
| **M2.5 前后端只读 API bridge** | 后端 HTTP API + 前端 API client；替换 `/monitor`、`/replay`、`/research`、`/trade` 的 mock hooks；补 loading/error/empty；真实下单 POST 继续关闭 | 四页面展示后端真实返回数据；mock 仅作测试/dev fallback；后端 API 测试 + 前端测试/build 通过 |
| **M3 情绪+单 agent 挖掘** | 情绪一期（聚合指标，北向/两融标"不宜反向"）、3a 单 agent（DSL+解释器）、实验追踪、市场宽度因子策略 | **工程 Done**：管线端到端可复现、门禁生效、实验落库；**命题裁决（go/no-go 报告）**：通过全门禁因子数、OOS IC 分布、与已知因子相关性；0 因子 → M6 暂缓 |
| **M4 实盘（多账户）** | 风控严肃层（档内分档）、拆单、告警、影子模式→小资金实盘、一致性校验（snapshot 重放）、灰度金丝雀 | **连续 20 交易日实盘对账差异 < 0.1%、最大回撤 < 配置阈值、滑点偏差 < 校准带** |
| **M5a 情景模拟与复盘（⑧）** | 反事实回放（边界声明）、次日情景（GARCH/DCC+过撮合）、每日复盘、三合一报表/复盘 UI | 复盘报告自动生成；GARCH/DCC 校准通过；VaR 95%/99% 回测覆盖率达阈值；复盘 UI 遵循 `DESIGN.md` token |
| **M5b 主体行为学习（⑨）** | Actor 样本库（标签=PnL）、三路学习（按 actor 切 OOS）、标准门禁 | 行为因子经标准门禁（BH-FDR+新颖性+经济显著+人审）入库；M3 同一门禁 |
| **M6 multi-agent + 社媒（可选，依赖 M3 命题 go）** | 3b multi-agent 闭环（子进程沙箱）、情绪二期（社媒，合规开关） | multi-agent 闭环可恢复 ≥ 50 轮；社媒因子增量贡献显著（用户显式开启后） |

---

## 12. 技术栈汇总

| 类别 | 选型 |
|---|---|
| 语言 | Python 3.11+ |
| 行情/交易 | xtquant（QMT/MiniQMT，pip 可装运行需登录，**M-1b 验证**）、Tushare/AkShare（历史/情绪） |
| 交易规则 | 官方交易所/中国结算/税务手工确认入库（M0.5），TradingRuleProvider 统一读取 |
| 数据处理 | pandas/numpy/numba |
| 存储 | SQLite(WAL)（事务）+ DuckDB（行情/因子/tick 分析） |
| 并发 | asyncio（盘中调度）+ ProcessPool（因子/策略 CPU offload）+ 独立写线程（SQLite）|
| 后端 API | FastAPI/ASGI（只做协议转换与门禁，不重写领域逻辑） |
| 组合优化 | cvxpy（QP/OSQP）+ 主板 100 股整数化；多 lot/MIQP（SCIP/Gurobi）作为后续扩展 |
| 情景模拟 | GARCH/EGARCH-t + DCC（arch 库或自实现） |
| 调度 | cron/systemd timer + 交易日历 wrapper（**移除 APScheduler**） |
| LLM | DeepSeek（主）、Claude/GPT（可选） |
| Agent | 自研轻量调度（状态落库） |
| 沙箱 | **DSL 手写解释器**（主）；Python 源码则子进程+seccomp/nsjail |
| NLP（情绪） | Chinese-FinBERT（中文金融语料，M-1a 验证）/ 规则兜底 |
| 实验追踪 | 自建 SQLite experiment 表（含 snapshot_id）→ MLflow |
| 密钥 | keyring（环境 namespace）+ age/gpg fallback + 环境互斥锁 |
| 前端/UI | Next.js + TypeScript + Tailwind；`DESIGN.md` 映射 theme/components；TanStack Query；lightweight-charts/recharts |
| 可视化 | 生产 UI 用 Next.js 仪表盘；研究/离线报表可辅以 Plotly/notebook |
| 配置 | YAML/TOML（部分热加载） |
| 测试 | pytest；Vitest/Testing Library；Next build |

---

## 13. 风险与遗留

| 风险 | 应对 |
|---|---|
| **xtquant 地基未验证** | M-1b go/no-go；M-1a 本地能力不被阻塞 |
| **一期 alpha 衰减** | 一期源（市场宽度）已被定价，差异化弱；一期验证目标=因子工程管线可运行+市场宽度因子 IC 是否显著（M3 判定），不宣称散户情绪反向；二期社媒才兑现资料 alpha |
| **回填段 PIT 不可证** | pit_confidence 标注；回测打标；关键源尽量用当时快照 |
| **交易规则写错/过期** | 官方来源+生效日+人工 golden cases+source_confidence；未 verified 禁实盘 |
| **历史规则回溯工作量大** | M0.5 独立预算；只回测 2020 后；规则表分批覆盖 |
| 回测过拟合 | BH-FDR（预算数）+ 锁死 holdout + 新颖性 + 百科查重 + 双门 |
| QMT 接口变动 | Broker 抽象+适配层单测 |
| 情绪/社媒合规 | 见 §16；二期默认关闭+知情开关 |
| LLM 复述已知因子 | DSL+百科查重+新颖性 |
| SQLite/DuckDB 写并发 | 独立写线程+单写进程交接+跨进程协调 |
| 实盘-回测偏差 | 接口共用+摩擦校准+实盘落 tick+snapshot 重放一致性校验 |
| 多账户隔离 | account_id 维度+环境互斥锁+对账多账户 |
| 数据损坏/误覆盖 | 每日快照+dry-run+可回滚 |
| 免费数据源不稳定 | 多源校验+source_audit+降级策略 |

**遗留待定**：具体券商开户（M-1b）；DeepSeek vs Claude/GPT 因子质量（M-1/M3）；交易规则初始覆盖范围（M0.5）；行为学习三路权重（M5b）；DSL 算子集最终范围（M3 前）；复盘报表指标集；GARCH/DCC 校准窗口（M5a）；λ/γ 设定方法（M1.5）。

---

## 14. 数据源与 API 选型清单

### 14.1 选型原则

1. **优先免费且准确**；付费仅在免费不足（L2/深度财务/机构实时）时引入。
2. **可配置可替换**：Provider 接口 + YAML 配置。
3. **多源校验**：关键数据交叉校验。
4. **PIT 可证明**：能给出/推导 available_at；不能证明的只用于研究。
5. **待验证项由 M-1a/M-1b 实测**。

### 14.2 选型清单（免费优先）

| 类别 | 用途 | 免费（优先） | 付费 | 一期推荐 | 准确性 | 备注 |
|---|---|---|---|---|---|---|
| 实时行情 | 盘中策略 | **QMT xtdata** | 第三方 L2（米筐/Wind） | QMT | 高 | M-1b 验证 |
| 历史日线/分钟 | 回测/因子 | **AkShare**/**BaoStock**/Tushare 免费积分 | Tushare Pro/Wind | AkShare+BaoStock 校验 | 中高 | 多源兜底 |
| 基础数据 | 全局 | **AkShare**+**exchange_calendars**+Tushare | Wind/Choice | AkShare+exchange_calendars | 中高 | 复权多源校验 |
| 交易日历（调休） | 调度 | **exchange_calendars**+AkShare+公告 overlay | — | exchange_calendars+overlay | 高 | 每年升级 |
| 交易规则 | 撮合/风控 | 交易所/中国结算/税务官方 | — | 自维护版本表（M0.5） | 高 | 不硬编码 |
| 龙虎榜 | ⑨ | **AkShare**/Tushare 免费积分 | Tushare Pro/Wind | AkShare | 中高 | 仅上榜样本 |
| 游资席位库 | ⑨ | 开源社区库/自建 | — | 自建+社区库 | 中 | 营业部聚类 |
| 资金流向/大单 | ⑨/流动性 | **AkShare** | Tushare Pro/L2 | AkShare | 中 | L2 需订阅 |
| 北向资金 | 趋势因子 | **AkShare**/Tushare | — | AkShare | 高 | **不宜作反向源** |
| 融资融券 | 趋势因子 | **AkShare**/交易所/Tushare | Wind | AkShare | 高 | **不宜作反向源** |
| 财务/估值 | 基本面因子 | **AkShare**/Tushare 基础/BaoStock | Tushare Pro/Wind | AkShare+Tushare | 中高 | 披露日 PIT |
| 市场情绪指标 | 情绪因子 | **AkShare**/行情自算 | — | 自算+AkShare | 高 | 非散户情绪 |
| 舆情/股吧（聚合） | 情绪因子 | 东财股吧（非官方，合规风险，仅研究） | 第三方舆情 API | 一期聚合指标+授权源 | 中 | 不存个人内容 |
| NLP 情绪 | 情绪打分 | **Chinese-FinBERT**（中文金融）/SnowNLP 兜底 | 百度/阿里 API | Chinese-FinBERT | 中 | M-1a 验证 |
| LLM | ③ 挖掘 | 开源本地（DeepSeek/Qwen 本地，需 GPU） | **DeepSeek API**/Qwen/GLM/Claude/GPT | DeepSeek API | 高 | M-1 实测 |
| 交易通道 | ⑥ 执行 | **QMT/MiniQMT** | 券商 OpenAPI（机构版） | QMT | 高 | M-1b 验证；easytrader 停更不推荐 |
| 模拟盘 | 验证 | **QMT 模拟**/聚宽模拟 | — | QMT 模拟 | 高 | 与实盘同通道 |

> 准确性：**高**=交易所/官方；**中高**=聚合可靠；**中**=需清洗/多源校验。

### 14.3 可配置实现

```yaml
# config/datasources.yaml
market_data:
  realtime: { provider: qmt, subscription: level1 }
  history:  [{ provider: akshare }, { provider: baostock, role: crosscheck }]
calendar: { provider: exchange_calendars, overlay: manual_holidays }
trading_rules: { provider: local_versioned, sources: [sse, szse, bse, chinaclear, tax] }
fundamentals: { providers: [{ provider: akshare }, { provider: tushare_free }] }
dragon_tiger: { provider: akshare }
sentiment: { market_indicators: { provider: akshare }, nlp_model: chinese_finbert }
llm: { provider: deepseek, model: deepseek-chat, fallback: qwen }
broker:
  paper: { provider: qmt, env: simulation }
  live:  { provider: qmt, env: production }
accounts: [{ account_id: acct1, broker: qmt, env: simulation }]
```

```python
class ProviderRegistry:
    def __init__(self, config: dict): ...
    def market_data(self) -> MarketDataGateway: ...
    def trading_rules(self) -> TradingRuleProvider: ...
    def broker(self, account_id: str) -> Broker: ...   # per-account
    def llm(self) -> LLMClient: ...
```

---

## 15. 官方规则与来源校验清单

> 约束实现，不代替法律意见。校验日期 2026-06-14。规则以 M-1a/M0.5 保存的官方原文快照为准，写入 `trading_rule.source_url` + `source_confidence`。

| 主题 | 当前结论 | 来源 / 状态 |
|---|---|---|
| 上交所主板规则 | 当前只取主板股票有效规则；2026 修订 2026-07-06 生效，当前不得当已生效硬编码 | sse.com.cn 官方页（**verified**，2026-06-16 source audit） |
| 深交所主板规则 | 当前只取主板股票有效规则；不得只按上交所推断 | szse.cn（**verified**，2026-06-16 source audit） |
| 北交所/科创/创业/ETF/可转债规则 | 不进入当前阶段实盘范围；后续扩展前单独补来源快照、fixture 与验收 | bseinfo.net / sse.com.cn / szse.cn（**deferred**） |
| 价格最小变动单位 | 当前主板股票 0.01 元；ETF/基金/可转债后续另表 | rule_json.price_tick by product_type |
| 申报数量 | 当前主板 100 股整数倍；科创/北交等后续另表 | rule_json.quantity_rule + fixture |
| 新股无涨跌幅 | 当前沪深主板注册制前 5 日；北交等后续另表 | rule_json.no_limit_window |
| 印花税 | 2023-08-28 减半，卖方 0.05%，配置化 | 税务系统公告转载（**verified**） |
| 过户费 | 0.001%，双边，配置化 | 中国结算公告权威转载（**verified**） |
| 经手费 | 0.00341%，双边，配置化 | 证监会降费安排（**verified**） |

> 状态：verified / pending / provisional。当前主板种子规则与公共费率已记录到 `docs/review/2026-06-16-trading-rule-source-audit.md`。实盘前所有规则须 verified；券商佣金属于 broker_configured，不按公开规则伪造固定值。

---

## 16. 数据合规清单（PIPL + ToS + 出境）

> 差异化能力依赖情绪数据，合规须可执行，非风险表一句话。

### 16.1 数据分类（字段级）

| 数据 | 类别 | 法律基础（PIPL §13） |
|---|---|---|
| 行情/龙虎榜/北向/两融（公开市场数据） | 非个人信息 | 法定公开 |
| 股吧/雪球聚合指标（讨论数/词频） | 匿名聚合 | 合理处理已公开信息（§27），**商业用途需评估"合理范围"** |
| 股吧/雪球原文（含昵称/内容） | 个人信息 | 需同意；一期**不采集** |
| 社媒私域（抖音/小红书群） | 个人信息+敏感 | 需同意；二期默认关闭 |
| 自身成交（QMT 导出） | 个人信息（本人） | 本人授权 |

### 16.2 处理-存储-销毁全链路

- **处理 ≠ 存储**：即便只算讨论数（先访问帖子），帖子含个人信息，处理即受 PIPL 管辖；"不存"≠合规。
- UGC 仅采集匿名聚合指标，**采集过程**仍需 ToS 合规清单。
- 保留期限 + 销毁策略（情绪聚合数据按交易日聚合后销毁原文引用）。
- **DPIA**（§55-56）：大规模个人信息处理需评估；二期社媒触发。

### 16.3 数据出境（PIPL §38）

- **LLM API 出境**：DeepSeek（国内，无出境）；Claude/GPT（境外，若送策略假设/市场数据触发出境合规）→ 需安全评估或仅送脱敏/非个人非重要数据。
- 实盘决策数据**禁止**送境外 LLM。

### 16.4 平台 ToS 矩阵

| 平台 | ToS 爬取条款 | 一期策略 |
|---|---|---|
| 东方财富股吧 | 限制商业爬取 | 仅公开 API/聚合，评估合理范围 |
| 雪球 | 禁止未授权 | 仅聚合或授权 |
| 抖音/小红书 | 禁止 + 反爬 | 二期，默认关闭 |
| **反不正当竞争法 2025 修订 §13** | 数据抓取新规 | 法务确认（**pending**） |

### 16.5 合规探测（M-1a）

法务确认一期各源可用性 + 出境评估 + DPIA 触发判定，写入合规配置。

---

## 附录 A：术语表

- **PIT（point-in-time）**：数据可用时点语义；实时段可证 / 回填段 `rule_inferred`。
- **factor_snapshot_id**：冻结的数据快照版本（as_of 集合），保证回测可复现；区别于 factor_version（代码版本）。
- **pit_confidence**：live（实时可证）/ rule_inferred（回填推断）。
- **三态同码（接口层）**：策略/风控/执行接口三态共用；撮合行为不对称需校准。
- **holdout 段**：锁死真 OOS，一次性永久锁，forward-walking 出新 holdout。
- **BH-FDR**：Benjamini-Hochberg 错误发现率校正，分母用假设预算数。
- **新颖性检验**：因子值 Spearman + 收益预测相关双查 > 0.5-0.7 拒绝；含已知因子百科查重。
- **T+N 结算**：接口保留 per-product 结算周期；当前阶段只做主板股票 T+1，其他品种后续扩展。
- **Actor**：行为主体（游资/自己/北向/机构）。
- **反事实回放**：改写决策观察差异；仅自身小单扰动保证撮合一致。
- **Shapley 归因**：公平分配多相关因子贡献的归因法。
- **GARCH/DCC**：波动聚集/肥尾 + 动态相关性的时间序列模型。
- **影子模式（Shadow）**：实盘行情驱动仅出建议不下单。
- **IC/IR/walk-forward/look-ahead/Brinson/Barra(CNE6)**：因子评价/归因术语。

---

## 附录 B：修订追溯

| 版本 | 修订 |
|---|---|
| v0.1→v0.2 | 红队复核：编号统一、M-1 探测、三态撮合诚实化、PIT 字段落表、规则版本化、风控前移、量化验收、资金档位量化 |
| v0.3 | §14 数据源选型清单（免费优先、Provider+YAML 可替换） |
| v0.4 | 交易规则版本化、A股规则修正、PIT 事实字段、因子版本/假设预算、M1 工程正确性验收、§15 官方规则来源 |
| **v0.5** | **四维度红队吸收**：一期宣称诚实化（市场宽度非散户情绪）、T+N per-product、多账户、因子中性化评价、factor_snapshot_id 可复现、PIT 实时/回填分级、组合优化标量化+gap、GARCH/DCC 情景、行为学习标签PnL+标准门禁、分层并发(ProcessPool+独立写线程+DuckDB交接)、DSL手写解释器沙箱、M-1拆a/b、TradingRule独立M0.5、§16数据合规、止损止盈/生命周期/再平衡/事件总线/bar去重/策略隔离、移除APScheduler、§15 URL状态列+过户费provisional |
| **v0.5-ui** | 将根目录 `DESIGN.md` 纳入系统设计，作为 UI token 与组件风格的权威配置源；补 §4.11 UI/前端设计系统、技术栈与路线图验收口径 |
| **v0.5-scope** | 当前阶段交易范围收窄为沪深主板股票；科创/创业/北交/ETF/可转债作为后续扩展，须补规则来源、fixture 与验收后再进入实盘 |
| **v0.5-api** | 补前后端 API 层、M2.5 只读 API bridge、`rules_for(require_verified)`、`data_snapshot.as_of_cap` 与 `trading_rule` no-overlap 应用层约束 |
