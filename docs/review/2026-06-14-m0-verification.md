# M0 后端 + 前端 验证报告

> 日期：2026-06-14　分支：`feat/m0-backend`（M0）/ `main`（UI 已并入）
> 对照：设计 v0.5 `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md`
> 范围：M0 后端基础设施（15 任务）+ UI Phase 1-4，比照设计文档验证功能完整性

---

## 1. 测试证据（全套绿）

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **105 passed, 1 xfailed, 4 deselected** |
| 后端 slow perf（DuckDB 5300 全市场） | 1 passed（横截面稳态 4.0ms，预算 50ms） |
| 前端 `next build` | **clean**，6 路由全部预渲染 |
| 前端 `vitest run` | **56 passed**（10 文件） |

xfail：`tests/probes/test_calendar_holidays.py::test_makeup_trading_day_is_trading_day` —— M-1a 探测记录的已知缺口（exchange_calendars 不识别补班日），**生产修复在 `quant/providers/calendar.py` overlay**（test_calendar + 集成验收均绿）。探测作历史记录保留。

---

## 2. 后端 M0 vs 设计 §11（验收 7 条逐条）

| 设计 §11 M0 验收 | 实现 | 证据 |
|---|---|---|
| 读写（SQLite+DuckDB CRUD） | ✅ Repository（Account/Position/Order via SqliteStore，Bar via DuckdbStore） | test_repository 15 测试 + 集成验收 1 |
| PIT 断言（available_at/pit_confidence） | ✅ quant/data/pit.py（live/rule_inferred 分级 + max 规则） | test_pit 8 测试 + 集成验收 2 |
| 规则按日取值（区间查询） | ✅ TradingRuleProvider（effective_from<=d<effective_to，NULL=无限期） | test_trading_rule 7 测试 + 集成验收 3 |
| 质量门禁拦截（deny-default） | ✅ DataQualityGate（缺失/OHLC/负值/z-score，未知 dataset DENY） | test_quality_gate 9 测试 + 集成验收 4 |
| 多账户隔离 | ✅ Repository account_id 维度（PK + WHERE） | 集成验收 5（acct1/acct2 双向隔离） |
| 调休日历 | ✅ TradingCalendar（exchange_calendars + MAKEUP_TRADING_DAYS overlay） | test_calendar 5 测试 + 集成验收 6 |
| 单测通过 | ✅ 97 测试 | pytest tests/quant |

**§11 M0 内容覆盖**：
- ✅ 项目骨架 + 配置（quant/config.py，YAML dataclass）
- ✅ SQLite+DuckDB+Repository（多账户）
- ✅ ProviderRegistry
- ✅ 事件总线（隔离订阅者）
- ✅ 日志（setup_logging）/ SecretManager（EnvSecretManager，keyring/age 留 M2）
- ✅ 日历（调休 overlay）
- ✅ 基础数据 schema（instrument 等 20 表，§6 全部 DDL）
- ✅ PIT 字段 + 事实字段（models + pit.py）
- ✅ trading_rule 表 + Provider
- ✅ 数据质量独立验证层

**写并发策略（§6）落实**：SQLite 独立写线程（queue.Queue + WAL + flush barrier + stop drain + 并发读锁）；DuckDB 单写协调（RLock）。根因修复了共享连接并发读竞态（c27acaa）。

---

## 3. 前端 UI vs 设计（4 路由）

| 路由 | 设计对应 | 实现 | 测试 |
|---|---|---|---|
| `/replay` | §4.8 复盘（K线+情绪+信号） | Phase 1：KlineChart（lightweight-charts）+ SentimentChart（recharts）+ ReplayReport | 含 |
| `/monitor` | §4.10/§4.4.4 监控 | Phase 2：PositionsTable/StrategyTable+LifecycleBadge(8态)/RiskPanel/AlertList/PnlOverview | 含 |
| `/trade` | §4.6 执行层（mock） | Phase 3：OrderForm（买/卖 trading-up/down + 快捷比例 + NaN 守卫）/OrdersList(6态)/FillsList/TradePanel | 含 |
| `/research` | §4.2.3/§4.7 因子评价+回测 | Phase 4：FactorEvalChart(IC+分层)/BacktestResultPanel(净值/回撤/归因)/StrategyLifecycleTable | 含 |

视觉：DESIGN.md 币安风格（深黑 #0b0e11 + 币安黄 + 涨绿跌红）→ Tailwind theme + next/font（Inter + IBM Plex Sans）。全部 mock 数据驱动，接真 API 时改 queryFn 即可。

---

## 4. 已知缺口（按路线图，非本次范围）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **M0.5** | trading_rule 规则表 v1 录入（沪深 A 股+科创/创业/北交+ETF，2020+）+ golden cases + source_confidence | 未做（独立 plan） |
| **M-1b** | xtquant/QMT 通道探测 | 未做（依赖券商开户） |
| **M1** | 因子引擎（中性化评价）+ 回测引擎（撮合/摩擦/A股规则/T+N）+ 基础风控 + snapshot 可复现 + 绩效归因 | 未做 |
| **M1.5** | 策略引擎 + 组合优化器 + 生命周期 + 再平衡 | 未做 |
| **M2** | 模拟盘主线（行情网关/Broker/on_fill/DuckDB 写权交接/对账） | 未做 |
| **M3-M6** | 情绪/单 agent 挖掘/实盘/情景模拟/主体学习/multi-agent | 未做 |

**M0 设计要点部分留接口/注释**：
- DuckDB 跨进程单写交接：进程内 RLock 已做，跨进程交接注释标注留 M2。
- SecretManager keyring/age fallback：EnvSecretManager 已做，fallback 留 M2。
- 数据质量 z-score：基础已做，MAD/修正 z-score 留 §4.1.6 增强。
- classify_symbol：A 股主板/科创/创业/北交/ETF 已映射，可转债/SZ ETF/B 股留 M0.5 完善。

---

## 5. 留待清理（/simplify 或后续）

- `PitConfidence` Literal 在 models.py + pit.py 重复定义（应统一 import）。
- registry `TypeVar("T")` 未真约束（泛型弱类型）。
- test_secrets 的 Protocol 性质断言依赖 metaclass 名（CPython 实现细节，升级风险）。
- commit message 全程英文（与 UI 分支一致，CLAUDE.md 偏好中文）——未重写历史，后续可统一。
- TradingRule check_no_overlap 为 O(n²)（M0.5 录入数据小，可优化为相邻比较）。

---

## 6. 结论

**M0 后端基础设施（设计 §11）全部实现并通过验收，97 单测 + 1 slow perf 绿；UI Phase 1-4 四仪表盘全部交付，56 测试绿，build 干净。** 前后端骨架完整，可进入 M0.5（规则录入）→ M1（因子/回测引擎）。每任务均经独立 reviewer（spec + quality）双检，关键并发路径（SQLite 写线程、共享连接读竞态）根因修复并压力验证。
