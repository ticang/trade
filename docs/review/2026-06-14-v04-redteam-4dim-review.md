# v0.4 四维度红队审阅综合报告

> 审阅对象：`docs/specs/2026-06-14-a-stock-quant-trading-system-design.md`（v0.4）
> 审阅方：4 个独立 Agent（需求设计 / 算法 / 架构 / 实现可落地性），与设计作者隔离
> 审阅日期：2026-06-14
> 本文件为四份报告的综合留痕（紧凑提炼，保留全部 Blocker/Major/Minor 标题、证据、建议）

---

## 综合结论

v0.4 工程骨架扎实（交易规则版本化、PIT 落表、M1 验收语义修正、风控前移），但四维度共发现 **14 个 Blocker 级问题**。最严重的几个属"地基级"：实盘并发模型、回测可复现性、A股撮合现实性、风控规则穿透、差异化 alpha 自洽性。照 v0.4 实现，会出现"回测数字看似对、结论系统性偏差"+"实盘延迟漂移/丢帧"+"宣称的差异化 alpha 不存在"。

---

## 一、需求设计维度

### Blocker

- **[需-Blocker-A] T+1 被硬编码为普适风控规则**（§1.3、§4.5），与可转债 T+0、部分 ETF T+0 冲突。v0.4 的规则版本化只穿透到数据层/撮合层，没穿透风控层。→ §4.5 改 per-product T+N，从 `TradingRuleProvider.rules_for().settlement` 取；§1.3 改"T+N 按品种规则表"。
- **[需-Blocker-B] 一期情绪源（涨跌停家数/连板/北向/两融）不是"散户情绪"**，是市场宽度/机构因子；北向是聪明钱，对其反向 = 反 alpha。一期差异化 alpha 实质空心化，但 §0/§1.2 仍把它当一期核心卖点。→ 诚实改写一期宣称（市场宽度因子 ≠ 散户情绪反向）；§13 增"一期 alpha 衰减风险"；北向/两融标"不宜作反向源"。

### Major

- **[需-Major-C] §2.1 缺三类基础交易能力**：①止损止盈（Signal 无 stop/take-profit 语义，风控基础层无单仓位止损）；②策略生命周期管理（无 draft→paper→approved→live→degraded→offline 状态机+门禁）；③组合再平衡频率（优化器存在但"何时再优化"未定义）。
- **[需-Major-D] M3"不承诺入库数量"使 Done 混淆"工程通过"与"命题成立"**。→ 拆 M3 工程 Done + 命题裁决（0 因子入库 = 命题证伪，应触发 M6 暂缓）。
- **[需-Major-E] PIPL 合规只一句话**（§2.2/§13/§4.1.2）。缺数据分类清单、法律基础 per 源、LLM API 出境评估（PIPL §38）、处理-存储-销毁全链路、DPIA。→ 新增独立合规章节。
- **[需-Major-F] §1.4 资金档位 50 万边界与 MiniQMT 开户门槛矛盾**（50 万恰是头部券商门槛，小资金<50 万可能开不了户）。
- **[需-Major-G] position 表无 account 维度**（`symbol PRIMARY KEY`），单账户模型，多账户不支持。→ 加 account_id 或在非目标显式排除。
- **[需-Major-H] ⑧⑨被当核心目标实为远期增强**，定位膨胀（⑨三路并行是3子项目，但游资/北向同样样本不足；跳跃扩散/Barra/MIP 偏机构级）。
- **[需-Major-I] 50 万–1000 万合并单档过粗**，严肃层参数无档内缩放（50 万 vs 1000 万流动性/暴露容忍差 20 倍）。

### Minor
M1 sanity 无阈值边界；M3"人审"在单用户=自审独立性弱；M5a"达标"未定义；税务/股息红利报表；资金划转/打新冻结无建模；打新是否支持未表态；Barra/MIP 对个人偏重（YAGNI）；§3.3"接口不暴露任何存储特性"过强；TWAP/VWAP 在零售通道有效性存疑；复权方式未与 factor_version 绑定。

---

## 二、算法 / 统计维度

### Blocker

- **[算-Blocker-A] 因子评价未做行业/市值中性化**（§4.2.3）。原始 IC 把 alpha 与 size/industry beta 混在一起，系统性高估因子增量价值；未指定 Spearman/Pearson；IR 未做 Newey-West；缺经济显著性下限。→ 强制中性化残差上算 rank IC；报 NW 调整 t 统计；双门（统计显著 + 经济显著）。
- **[算-Blocker-B] PIT 多版本选择制造"回测随运行时间漂移"**（§4.1.5/4.2.2）。`available_at` 对回填数据是规则推断（非事实），多 as_of 版本让同一段历史回测今天跑 vs 一年前跑结果不同——不可复现；实盘永远取最新修订版，与回测隐性不一致；`factor_version`(代码) 与数据快照版本混淆。→ 引入 `factor_snapshot_id`（冻结的 as_of）；区分代码版本/数据快照；available_at 对 tick 取 received_ts。
- **[算-Blocker-C] 组合优化多目标权重未定义 + 整数化修复质量无界**（§4.4.3）。`max α'w − λ·TE² − γ·turnover` 的 λ/γ 完全决定策略行为却无设定方法；基准未定；round 后约束违反修复次优性无界；MIQP 开源求解器弱。→ 明确标量化公式+λ/γ 设定；定义基准；强制报告 QP 解 vs 整数化 gap；命名求解器+超时兜底。
- **[算-Blocker-D] GBM+跳跃扩散与 A 股撮合现实性根本冲突**（§4.8.2）。涨跌停截断（GBM 无）、T+1 与路径交互、肥尾/波动聚集（GBM 常波动）、相关性时变（文档目标 vs 单矩阵自相矛盾）、AI 预测融合数学缺失。→ 用 GARCH/EGARCH-t + DCC 相关；路径强制过撮合模拟器；AI 融合给显式公式防双重计数。

### Major
- **[算-Major-1] 防过拟合**：FDR 分母应用预算数非实际数（防 optional stopping）；holdout"冷却"措辞危险（应一次性永久锁，forward-walking）；walk-forward（选模型，非OOS）与 holdout（真OOS）需区分；跨三路候选缺族级 FDR；Bonferroni vs BH-FDR 未选型（默认 BH-FDR）。
- **[算-Major-2] 新颖性 0.9 阈值无效**（应 0.5–0.7）；用因子值 Spearman + 收益预测相关双查；LLM 复述训练集已知因子未防（需已知因子百科 Alpha101/GPO 查重）。
- **[算-Major-3] 行为学习**：ML 标签前视（标签应为 actor 实现 PnL，特征 PIT）；龙虎榜样本选择偏差（仅上榜股，Heckman 偏差）；"两路共识"误当独立样本防过拟合（三路同源数据非独立）；AI 归纳喂③循环。
- **[算-Major-4] 绩效归因**：Brinson 基准未定；多策略相关因子分解病态（共线下顺序 Brinson 不稳定，应用 Shapley/正交化回归归因）；Barra 版本未指定（CNE6）。
- **[算-Major-5] 反事实回放**对 actor 移除用例撮合一致性不成立（游资单正是上榜原因，移除→价格路径变，需价格冲击模型）。自身小单扰动有效。
- **[算-Major-6] LLM 温度/种子"确定性可复现"对商用 API 不成立**（批次采样/负载均衡/版本漂移）。→ 改固定模型版本快照 + 测 run-to-run 方差。

### Minor
分层回测分组/换手口径未定；因子衰减 forward return 重叠偏差；换手硬约束 vs 惩罚项混用（信号翻转大时 QP 不可行）；DSL 现有算子 PIT 安全未测；规则 fixture 缺复权断裂端到端用例；经济显著性下限缺失；跨路族级 FDR；校准窗口/N 收敛准则缺。

---

## 三、架构维度

### Blocker

- **[架-Blocker-A1] 实盘主线单 asyncio 循环承载阻塞 CPU 计算**（§7.1）。因子计算是 pandas/numba 同步 CPU-bound，会阻塞循环；全市场横截面算子让单 bar 触发全市场重算；无 backpressure/丢帧策略；SQLite 单写协程与决策共享循环。→ 因子/策略 offload 到 ProcessPoolExecutor/独立进程；网关层背压；SQLite 写移独立线程；§2.2 NFR 按作用域拆分。
- **[架-Blocker-A2] PIT `available_at` 对回填数据无法证真**（§4.1.5）。M0/M1 回填的历史数据是"今天的视图"，强制写 `available_at=当时` 是假设；运行时锚对回填段永远通过，制造"已防前视"的虚假正确性。→ 区分实时段（PIT 可证）vs 回填段（`pit_confidence=rule_inferred`）；回测打标；回填尽量用当时快照。
- **[架-Blocker-A3] DuckDB 跨进程并发写未处理**（§6/§9）。盘中进程落 tick + 盘后进程批量算因子，DuckDB 本地文件单进程独占写锁。→ 连接交接协议；或盘后写临时文件再合并；M-1 实测双进程并发写。

### Major
- **[架-Major-B1]** 横截面算子（rank/zscore/group_neutral）使单 bar 因子计算退化为全市场重算，无增量截面快照机制。→ 维护 in-memory 当前截面快照。
- **[架-Major-B2]** 单 SQLite 写队列与决策共享 asyncio 循环，下单突发挤占决策延迟。→ 写移独立线程。
- **[架-Major-B3]** `BarContext`/`FactorContext` 未定义，§5 契约表不完整，PIT/规则/因子如何注入 on_bar 无契约。→ 补 ctx 字段契约 + StrategyRunner 装配职责。
- **[架-Major-B4]** 三态共用在 ctx 持仓新鲜度（实盘延迟/在途未回写）和 Broker 同步/异步阻抗（SimBroker 同步 vs QmtBroker 异步回报）未闭合。
- **[架-Major-B5]** 数据质量门禁由数据层自产自销（生产者即把关者）。→ 提为独立验证层，deny-by-default。
- **[架-Major-B6]** 三轴版本化（factor_version+rule_version+as_of）M0 全量承诺与最小必要质量冲突，存储/查询成本未分析。→ 小资金档单 as_of+修订日志，多版本延后。
- **[架-Major-B7]** 无事件总线，线性管道新增 bar 消费者需改网关。→ 轻量进程内事件总线。
- **[架-Major-B8]** 无 bar 级幂等/去重，断线重连重发 bar 触发重复信号。→ bar 带唯一键去重 + 策略按目标持仓差分下单。
- **[架-Major-B9]** §15+规则版本化使 trading_rule 必须预置历史规则全集，M0 隐藏工作量未量化（历史规则无现成 API，需人工回溯）。→ M0 拆"历史规则回溯"子任务并量化；只回测 2020 后。
- **[架-Major-B10]** 三进程共享 SQLite+DuckDB，跨进程写协调未声明（单写队列是进程内原语，跨进程无效）。→ 显式跨进程写协调。
- **[架-Major-B11]** 无策略隔离边界，buggy 策略污染生产管道。→ 每策略 try/except+超时+研究策略默认影子模式。

### Minor
可演进性/平滑迁移过度表述（接口是进程内函数形状，迁分布式是重写）；调度器边界含糊（谁是"今天是否交易日"真相源）；调休补班覆盖待验证；Clock 未进契约表；组合优化器与风控数量校验职责重叠；配置热加载缺失；灰度金丝雀缺失；experiment 与 factor_value 跨库软外键。

---

## 四、实现可落地性维度

### Blocker

- **[实-Blocker-A] TradingRuleProvider 初始覆盖+维护被低估为配置项**（§4.1.3/§8/§15）。实则是高工程量、高风险、无 owner 的子系统：规则文本 PDF 不是结构化数据需人工录入；无权威来源项（过户费）未工程化处理；规则变更回归测试构成循环验证（用规则表验规则表）；effective 区间查询复杂度未测。→ 升级为独立子模块 M0.5 + 独立 owner + 三方校对 + 人工标注 golden cases + source_confidence 标志。
- **[实-Blocker-B] M-1 探测五合一过宽**（通道+数据源+规则+DeepSeek+性能），无法快速 go/no-go。本地几小时能证伪的项要等数周开户。→ 拆 M-1a（纯本地 1-3 天快速 go/no-go）+ M-1b（外部通道数周并行）。
- **[实-Blocker-C] RestrictedPython + LLM DSL 沙箱在真实因子工程不成立**（§4.3.4/4.3.5）。两套互斥执行模型混用（DSL 需手写解释器 vs RestrictedPython 执行 Python 源码）；RestrictedPython 不能表达 pandas/numba 向量化（链式属性访问白名单一放宽=无沙箱）；signal.alarm 在 asyncio 下冲突。→ 明确选 DSL 路线（手写算子解释器，PIT/缺失值/向量化在解释器层解决），删 RestrictedPython 作主沙箱；若保留 LLM 产 Python 源码改子进程+seccomp/nsjail。

### Major
- **[实-Major-1]** 组合优化 round+修复启发式未给算法；MIP 求解器选型与"中等规模"档位不匹配（开源 MIQP 数百整数变量可能超时，击穿<1s）；科创 200/北交递增 1 股是多 lot 约束非简单 round。
- **[实-Major-2]** DuckDB 单写者与盘中 tick 落盘冲突（DuckDB 连接 ~20ms 开销，单写锁）；§6 并发策略只覆盖 SQLite。→ tick 先内存/SQLite WAL + 异步批量 append DuckDB，或 tick 落 Parquet 盘后注册。
- **[实-Major-3]** 密钥管理".env+OS keychain"过笼统；多环境隔离缺失；MiniQMT 认证是客户端登录态非 API key（keychain 模型不适用）。→ keyring + 环境分 namespace + 环境互斥锁。
- **[实-Major-4]** APScheduler 即便轻量仍有 asyncio 集成风险。→ 移除 APScheduler，用 cron/systemd + 交易日历校验 wrapper；每年升级 exchange_calendars 跑日历回归。
- **[实-Major-5]** §15 URL 真实性待验证（深交所 2018 PDF 非现行规则）；过户费明确无权威来源但 §8 写成确定规则。→ URL 加状态列（verified/pending/provisional）；过户费改 provisional。
- **[实-Major-6]** 里程碑量化标准测量方法未定义：对账差异口径、FDR 的 p 值与 N 计数时机、连续 20 日判定（节假日/停牌）、look-ahead 运行时锚对 LLM 绕过 ctx 直接读库。→ 每条附测量脚本契约；因子代码强制经 ctx 访问数据。

### Minor
xtquant 已在 PyPI（pip 可装，运行需 miniQMT 登录）；easytrader 事实停更（建议删除或标"不推荐"）；MiniQMT 门槛国金~10 万（可大幅降低 M-1b 门槛）；FinBERT 是英文版，中文需 Chinese-FinBERT（待 M-1a）；trading_rule 缺区间不重叠约束；experiment 表 hypothesis_budget 语义（预算 vs 已用）需拆；computed_at 字段作计算完成时间 ground truth。

---

## 五、待验证项汇总

| 断言 | 待验证点 |
|---|---|
| MiniQMT 各券商门槛 | 50 万是否主流；国金~10 万是否可开 |
| xtquant 订阅频率/回调线程/断线重连是否重发 bar | M-1a/b 实测 |
| DuckDB 双进程并发写 + 高频 append 延迟 | 本地实测 |
| asyncio 单循环载全市场因子面板的延迟分布 | 实测 |
| RestrictedPython 能否跑 rolling+rank+group_neutral 真实因子 | 预期不能 |
| PIT 回填数据可证性边界 | AkShare/Tushare 是否提供历史发布日查询 |
| §15 URL 真实性 | 深交所 2018 PDF、过户费转载、2026-07-06 新规页 |
| DeepSeek 产出 Alpha101 变体频率 | M-1/M3 小样本实测 |
| 商用 API temperature=0 的 run-to-run 方差 | 实测 |
| 中文金融情绪模型（Chinese-FinBERT）在 A 股效果 | M-1a |
| exchange_calendars 调休补班覆盖 | 2024-2026 实测 |
| 反不正当竞争法 2025 修订对数据抓取约束 | 法务确认 |
| 可转债/各 ETF T+0 准确清单 | 多源交叉 |

---

## 六、跨维度战略级问题（需用户决策，非纯技术修订）

1. **一期差异化 alpha 空心化**（需-Blocker-B）：一期源无法兑现"散户情绪反向"。是否诚实改宣称、调整项目立意？
2. **⑧⑨定位**（需-Major-H）：是否降为远期增强，一期聚焦因子挖掘管线 + 基础交易？
3. **蒙特卡洛模型深度**（算-Blocker-D）：GBM 起步 + 涨跌停截断处理，GARCH/DCC 延后？还是直接上？
4. **多账户**（需-Major-G）：一期单账户数据模型预留 account_id，还是明确排除？
