# 设计文档修订计划

---

## [历史] v0.4 需求设计复核与修订计划（已完成）

### 目标
把 `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md` 从 v0.3 修订为 v0.4，重点从需求设计、算法、架构、实现可落地性四个维度收敛为可进入 M-1/M0 的版本。

### 任务清单
- [x] 复核官方交易规则与关键可变政策，修正 A 股交易规则表和数据源假设。
- [x] 补强 PIT 数据语义与数据模型，让前视防护能在实现层落地。
- [x] 审阅算法设计，收紧因子挖掘、情绪因子、行为学习、情景模拟的验收口径。
- [x] 审阅架构边界，补清 Provider、Repository、Broker、规则引擎、调度与可观测性的实现约束。
- [x] 重写 v0.4 修订要点、风险、路线图和验收标准，形成主文档 v0.4。
- [x] 自检文档一致性，补充 review 结论。

### Review
已完成 v0.4 主文档修订。关键结论：
- 交易规则不能硬编码，尤其价格 tick、申报数量、新股无涨跌幅窗口、过户费，需要按市场 / 品种 / 生效日期取版本化规则。
- PIT 需要落到事实表字段，`pit_field` 只能做规则注册，不能替代每条数据的 `available_at/source/ingested_at/as_of`。
- M1 应验收回测与规则引擎正确性，不能用"夏普 > 某阈值"作为基础设施完成标准。
- AI 因子挖掘应使用假设预算、FDR、新颖性、交易成本后收益和人审入库，不承诺固定入库数量。
- M-1 除 xtquant 外，还必须验证免费数据源覆盖率、字段延迟、规则来源快照和规则 fixture。

---

## v0.5 修订计划（进行中）

> 来源：v0.4 四维度红队审阅（`docs/review/2026-06-14-v04-redteam-4dim-review.md`）
> 目标：综合四份独立报告，修订设计文档出 v0.5
> 原则：无争议技术修订直接做；战略级问题等用户决策

### 战略决策点（待用户拍板，影响 v0.5 根本写法）

- [ ] **1. 一期 alpha 宣称**（需-Blocker-B）：一期情绪源是市场宽度（非散户情绪），差异化 alpha 空心化。处理方式？
- [ ] **2. ⑧⑨ 定位**（需-Major-H）：情景模拟+行为学习是否降为远期增强？
- [ ] **3. 蒙特卡洛深度**（算-Blocker-D）：GBM 起步 vs 直接 GARCH/DCC？
- [ ] **4. 多账户**（需-Major-G）：预留 account_id vs 明确排除？

### 无争议技术修订（直接落实到 v0.5）

#### 需求设计
- [ ] [需-Blocker-A] T+1 → per-product T+N，从 `TradingRuleProvider.settlement` 取；§1.3/§4.5/§8 同步
- [ ] [需-Major-C] 补三类基础能力：止损止盈（Signal + 风控基础层）、策略生命周期状态机+门禁、再平衡频率（触发模式可配置）
- [ ] [需-Major-D] M3 拆"工程 Done"+"命题裁决（go/no-go）"
- [ ] [需-Major-E] 新增 §16 数据合规清单（数据分类/法律基础/LLM 出境/处理-存储-销毁/DPIA）
- [ ] [需-Major-F] §1.4 档位边界与开户门槛解耦
- [ ] [需-Major-G] position/orders/fills 加 account_id（多账户预留或非目标显式排除）
- [ ] [需-Major-I] 中等规模档内分 2-3 子档，严肃层参数 per-子档默认值
- [ ] Minor：M1 sanity 边界、M5a"达标"阈值、打新/税务表态、Barra/MIP YAGNI 标注

#### 算法 / 统计
- [ ] [算-Blocker-A] 因子评价强制中性化残差 + rank IC + Newey-West + 经济显著性双门
- [ ] [算-Blocker-B] 引入 `factor_snapshot_id`（冻结 as_of），区分代码版本/数据快照；available_at 对 tick 取 received_ts
- [ ] [算-Blocker-C] 组合优化明确标量化公式 + λ/γ 设定 + 基准 + QP-vs-整数化 gap + 求解器命名+超时
- [ ] [算-Blocker-D] 蒙特卡洛按战略决策（GBM+截断起步 / GARCH+DCC）；路径强制过撮合模拟器；AI 融合显式公式
- [ ] [算-Major-1] FDR 分母用预算数；holdout 一次性永久锁（删"冷却"）；walk-forward vs holdout 区分；跨路族级 FDR；默认 BH-FDR
- [ ] [算-Major-2] 新颖性阈值降至 0.5-0.7；因子值+收益预测双查；建已知因子百科查重
- [ ] [算-Major-3] 行为学习标签=actor 实现 PnL（PIT）；龙虎榜标"仅高波动子集"；删"两路共识入库"改标准门禁；按 actor 切 OOS
- [ ] [算-Major-4] 归因基准定义；多策略相关因子用 Shapley/正交化；Barra 命名 CNE6
- [ ] [算-Major-5] 反事实回放界定用例边界（自身小单有效，actor 移除需冲击模型）
- [ ] [算-Major-6] LLM 确定性改"固定模型版本+测 run-to-run 方差"

#### 架构
- [ ] [架-Blocker-A1] 分层并发：因子/策略 offload ProcessPool/独立进程；网关背压；SQLite 写移独立线程；§2.2 NFR 按作用域拆
- [ ] [架-Blocker-A2] PIT 区分实时段（可证）vs 回填段（pit_confidence=rule_inferred）；回测打标
- [ ] [架-Blocker-A3] DuckDB 单写进程交接协议；M-1 实测双进程并发
- [ ] [架-Major-B1] 盘中增量截面快照机制
- [ ] [架-Major-B3] 补 BarContext/FactorContext 契约 + StrategyRunner 装配职责 + Clock 进 §5
- [ ] [架-Major-B4] ctx 持仓新鲜度 + Broker 同步/异步阻抗（on_fill 回调模板）
- [ ] [架-Major-B5] 数据质量门禁提为独立验证层
- [ ] [架-Major-B6] 版本化分档（小资金单 as_of + 修订日志）
- [ ] [架-Major-B7] 进程内事件总线
- [ ] [架-Major-B8] bar 级去重 + 目标持仓差分下单
- [ ] [架-Major-B9] M0 拆"历史规则回溯"子任务并量化；只回测 2020 后
- [ ] [架-Major-B10] 跨进程写协调声明
- [ ] [架-Major-B11] 策略隔离（try/except+超时+研究策略默认影子）
- [ ] Minor：可演进性降级表述、调度器边界、调休数据源、配置热加载、灰度金丝雀

#### 实现可落地性
- [ ] [实-Blocker-A] TradingRuleProvider 升级独立子模块 M0.5 + owner + 三方校对 + 人工 golden cases + source_confidence
- [ ] [实-Blocker-B] M-1 拆 M-1a（本地 1-3 天）+ M-1b（外部通道）
- [ ] [实-Blocker-C] 沙箱选 DSL 路线（手写解释器），删 RestrictedPython 主沙箱
- [ ] [实-Major-1] 组合优化 round+修复算法具体化 + 多 lot 约束 + 求解预算
- [ ] [实-Major-2] tick 落盘：内存/SQLite WAL + 异步批量 append DuckDB，或 Parquet
- [ ] [实-Major-3] 密钥：keyring + 环境 namespace + 互斥锁；MiniQMT 认证说明
- [ ] [实-Major-4] 移除 APScheduler，cron/systemd + 交易日历 wrapper
- [ ] [实-Major-5] §15 URL 加状态列；过户费改 provisional
- [ ] [实-Major-6] 里程碑量化标准附测量脚本契约；因子代码强制经 ctx

### 执行顺序

1. 用户拍板 4 个战略决策点
2. 综合战略决策 + 全部技术修订，重写 v0.5
3. 附录 B 补 v0.4→v0.5 修订追溯
4. 自检（占位符/一致性/范围/歧义）
5. 用户审 v0.5

### 状态

战略决策点（用户已拍板）：① 诚实改宣称 ② 保持 M5（⑧⑨ 不降格）③ 直接上 GARCH/DCC ④ 一期就支持多账户。全部技术修订项（约 40 项）已在 v0.5 落实。

### review

**任务目标**：综合四维度独立红队审阅 + 用户战略决策，将设计文档从 v0.4 修订为 v0.5。

**结果**：
- v0.5 已写入 `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md`（含 16 节 + 附录，新增 §16 数据合规清单）。
- 落实 4 战略决策：一期宣称诚实化（市场宽度非散户情绪，北向/两融标"不宜反向源"）、⑧⑨ 保持 M5、情景模拟改 GARCH/EGARCH-t + DCC、多账户支持（account_id 贯穿数据模型/接口/对账）。
- 落实 ~40 技术修订（按四维度），关键：T+1→per-product T+N、因子中性化评价+rank IC+NW+经济双门、factor_snapshot_id 可复现、PIT 实时/回填分级、组合优化标量化+λ/γ+gap+求解器、行为学习标签=PnL+标准门禁（删两路共识）+按actor切OOS、分层并发(ProcessPool+独立写线程+DuckDB交接)、DSL手写解释器沙箱、M-1拆a/b、TradingRule独立M0.5、止损止盈/策略生命周期/再平衡、进程内事件总线、bar去重、策略隔离、移除APScheduler、§15 URL状态列+过户费provisional。
- 附录 B 补 v0.4→v0.5 修订追溯。
- 自检：占位符仅剩 M-1a 待实测的量化值（X ms/Y 秒/sanity 边界），已标注待定；编号/接口/数据流交叉一致；范围聚焦；无歧义。

**遗留风险**：
- v0.5 部分内容（GARCH/DCC、Barra CNE6、MIQP、Shapley 归因、Chinese-FinBERT）是较重的实现，M5a/M5b/M0.5 时需验证工作量与收益匹配。
- 一期 alpha 弱（市场宽度已被定价），项目立意依赖二期社媒兑现"散户情绪反向"——这是已知战略风险，已在 §13 显式标注。
- 多账户 + GARCH + 沙箱子进程等增加了实现复杂度，需在 M-1a/M0 早期用最小原型验证不阻塞。

**后续建议**：
1. 用户审 v0.5（尤其 §16 合规、§4.4 止损止盈/生命周期、§11 M-1a/M-1b/M0.5 路线图）。
2. 审通过后进入 writing-plans，从 M-1a 本地探测脚本开始拆开发任务。
3. v0.5 文档建议 commit（可开分支），与 v0.4 红队报告一同留痕。

---

## M-1a 本地技术探测结论（已完成）

**报告**: `docs/review/m1a-report-2026-06-14.md`

**结论: GO** — 地基假设全部验证，可进入 M0。

**结果明细**:
- PASS: DuckDB 横截面延迟(<50ms)、SQLite 单写队列(0 lock/高吞吐)、DSL 解释器(rank(ts_mean))、Chinese-FinBERT(看涨>看跌)
- 已知可接受失败 (2，非阻断):
  1. Calendar 调休补班(2024-02-04): exchange_calendars 未覆盖 → **M0 待办**：实现调休 overlay
  2. AkShare live fetch: 当前网络出口无法访问 eastmoney → **M0 待办**：在中国网络环境复验（baostock 字段 + PIT 推导已 PASS，证明探测逻辑正确）

**带入 M0 的具体任务**:
- [ ] 实现交易日历调休补班 overlay（v0.5 §4.1.3 已预留机制）
- [ ] 在中国网络环境复验 AkShare 日线字段，确认数据源选型
- [ ] DuckDB 全市场 5300 票规模实测（M-1a 用 1000 票代表规模外推）

---

## M0 延期待办（M-1a 带入，非阻断）

- AkShare 中国网络复验：M-1a 探测 eastmoney 出口不可达，需在中国网络环境下复验 akshare 字段完整性（M2 实盘前必做）。
- 调休 overlay 维护：quant/providers/calendar.py 的 MAKEUP_TRADING_DAYS 为人工维护，需按交易所年度公告同步补录 2025+ 补班日。
