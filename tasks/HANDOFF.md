# 交接文档：A 股量化自动交易系统

> 更新：2026-06-15
> 状态：设计 v0.5 完成 + M0/M0.5/M1/M1.5/M2/M3/M5/M6 多数后端能力就位 + 前后端只读 API bridge 完成。剩余重点：连续模拟盘/实盘灰度门禁、规则三方校对、稳定外部数据源复验、真实研究样本复验。

---

## 1. 新会话如何开始

1. 读本文件（`tasks/HANDOFF.md`）+ `tasks/todo.md`
2. 读设计文档 `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md`（v0.5）+ `DESIGN.md`（币安风格 UI 规范）
3. 选下一个工作块（见 §5 剩余工作），读/写对应 plan
4. 按 CLAUDE.md 工作流执行：Spec Coding → writing-plans → subagent-driven（implementer + spec/quality review）

---

## 2. 分支结构

- **`main`**：UI Phase 1-4 + 早期 probes（duckdb_perf/sqlite_write）已 fast-forward 并入（dc563d9），后续本地又推进了后端能力、只读 API bridge、QMT 只读探测与 P1 本机项；当前工作区有未提交改动，先看 `git status`。
- **`feat/ui-phase1`**：已并入 main（与 main 同点 dc563d9），可安全删除。
- **`feat/m1a-local-probes`**：M-1a 完整探测（DSL/calendar/nlp/data_sources/report）+ m1a-report + tasks/todo.md。历史起点保留；当前执行口径以 `tasks/todo.md` 的“当前缺口总览”为准。

切换分支注意：`web/next-env.d.ts` 是 Next 自动生成，切分支前若有本地修改用 `git checkout -- web/next-env.d.ts` 丢弃。

---

## 3. 关键文档清单

| 文档 | 路径 | 用途 |
|---|---|---|
| 系统设计 v0.5 | `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md` | 16 节 + 附录，含路线图 M-1a→M6 |
| 红队报告 v0.1 | `docs/review/2026-06-14-design-redteam-review.md` | v0.1 对抗性复核 |
| 红队报告 v0.4 四维度 | `docs/review/2026-06-14-v04-redteam-4dim-review.md` | 需求/算法/架构/实现四维度 |
| M-1a go/no-go 报告 | `docs/review/m1a-report-2026-06-14.md` | 后端地基探测结论 |
| 参考资料 | `docs/reference-notes.md` | 资料.docx 经验提炼 |
| UI 设计规范 | `DESIGN.md`（项目根） | 币安风格 token 系统 |
| Plans | `docs/superpowers/plans/` | M-1a、UI Phase 1/2 plan |
| 任务跟踪 | `tasks/todo.md` | 修订计划 + review 段 |

---

## 4. 已完成工作

### 设计（v0.5）
- 经 4 轮独立红队审阅（v0.1 红队 + v0.4 四维度）吸收，含：交易规则版本化、PIT 数据语义、因子中性化评价、factor_snapshot_id 可复现、组合优化标量化、GARCH/DCC 情景、多账户、DSL 沙箱、分层并发、§16 数据合规清单等。
- 战略决策：一期 alpha 诚实化（市场宽度非散户情绪）、⑧⑨ 保持 M5、GARCH/DCC、多账户。

### M-1a 后端探测（GO）
8 任务全完成，6 探测：4 PASS + 2 已知可接受失败。
- DuckDB 横截面 1ms（48x 余量）· SQLite 单写队列 90k rps 无锁 · DSL 解释器路线可行 · Chinese-FinBERT 看涨>看跌
- 已知失败（非阻断）：exchange_calendars 不识别调休补班（M0 overlay）· AkShare eastmoney 当前出口不可达（M0 中国网络复验）

### UI Phase 1（设计系统 + 复盘页）
- DESIGN.md → Tailwind theme（colors/typography/spacing/radius 全映射）+ next/font（Inter + IBM Plex Sans）
- 基础组件：Button（9 variants）/ PriceCell / MarketTable / Card / TopNav
- `/replay` 复盘页：K线+成交量+信号标注（lightweight-charts）+ 情绪曲线（recharts）+ 信号清单
- 10 单元测试，整体 review Approved

### UI Phase 2（监控面板）
- 监控类型 + mock + hooks（Position/Strategy/RiskState/Alert）
- PositionsTable（账户分组）/ StrategyTable + LifecycleBadge（8 状态）/ RiskPanel（仓位/回撤进度/熔断/行业暴露）/ AlertList（级别色）/ StatCard + PnlOverview
- `/monitor` 页面，34 测试，整体 review Approved

### UI Phase 3（交易终端）+ Phase 4（研究回测）
- Phase 3 `/trade`：OrderForm（买/卖 + 快捷比例 + 预览，输入 NaN 守卫）、OrdersList（6 状态色）、FillsList、TradePanel、TradeDashboard；模拟下单（不接 broker）
- Phase 4 `/research`：FactorEvalChart（IC 时序 + 10 分层）、BacktestResultPanel（净值/回撤/归因）、AttributionBars、StrategyLifecycleTable、ResearchDashboard
- Phase 1-4 合计 56 单元测试，build clean，整体验收通过；commits 至 dc563d9

---

## 5. 剩余工作 + 起点

### M0 后端基础设施（在 `feat/m1a-local-probes` 或新分支 `feat/m0-backend`）
- 设计 v0.5 §11 M0/M0.5：项目骨架、SQLite+DuckDB+Repository、ProviderRegistry、事件总线、PIT、trading_rule、数据质量验证层
- **M0.5 TradingRuleProvider**（独立子模块）：当前规则表 v1 仅录入沪深主板股票 + 主板 ST（2020 至今）+ 人工 golden cases + source_confidence；科创/创业/北交/ETF/可转债为后续扩展，补来源/fixture/验收前不进实盘范围
- M0 待办（M-1a 带入）：① 交易日历调休 overlay ② AkShare 中国网络复验 ③ DuckDB 全市场 5300 规模实测
- 后续 M1/M1.5/M2... 见设计 §11 路线图

---

## 6. 环境注意

- **只读 API bridge**：后端 `uvicorn quant.api.app:app --reload --port 8000`；前端 `NEXT_PUBLIC_TRADE_API_BASE_URL=http://localhost:8000 npm run dev`。当前仅 GET 只读接口，不接真实下单 POST。
- **QMT 只读 live probe**：安装可选依赖 `pip install -e ".[qmt]" --index-url https://pypi.org/simple` 后运行 `.venv\Scripts\python.exe -m probes.qmt_live`。该探测不会下单；需要先打开并登录 QMT 投研版/极简版，并配置 `QMT_USERDATA_PATH` 才能完成 trader 只读握手。
- **AkShare/Eastmoney 网络探测**：如本机系统代理导致 `push2his.eastmoney.com` 断连，可在 PowerShell 临时设置 `$env:NO_PROXY='*'; $env:no_proxy='*'` 后重跑 `tests\probes\test_data_sources.py -m network`。当前仍需稳定中国网络复验，不要把单次通过等同于生产可用。
- **pip 镜像坏**（清华 SSL）→ `pip install --index-url https://pypi.org/simple`
- **npm registry**：用 `--registry https://registry.npmjs.org`（全局 .npmrc 可能指向 npmmirror，audit 不工作）
- **Python**：`.venv`（3.11.5），Windows 后端用 `.venv\Scripts\python.exe -m pytest`
- **Node**：v24，前端在 `web/`，`npx next build` / `npx vitest run`
- **目录**：`web/`（前端）、`probes/`（M-1a 探测）、`docs/`（设计+报告）、`tasks/`（跟踪）

---

## 7. 工作流约定（CLAUDE.md）

- **Spec Coding**：实现前必有规范（plan/设计）
- **subagent-driven**：implementer + spec review + code quality review，每任务
- **实现与审查分离**：禁止自我审查，指派独立 Agent
- **tasks/todo.md**：跟踪 + review 段（任务目标/结果/遗留/后续）
- **commit**：不留 AI 痕迹（无 claude/GPT/Co-Authored-By）；commit message 简洁
- **简洁优先**：YAGNI、最小影响面、孤儿导入清理
- **语言**：代码注释英文；文档可中文

---

## 8. 关键技术决策（已锁定，新会话遵循）

- 前端：Next.js 14 + TS + Tailwind + TanStack Query + lightweight-charts + recharts
- 后端：Python 3.11+ + SQLite(事务) + DuckDB(分析) + asyncio + DeepSeek API + DSL 手写解释器沙箱
- 交易通道：QMT/MiniQMT（只读行情/trader 握手已在 Windows + QMT 登录态通过；下单/撤单/断线恢复/连续模拟盘仍待 M2/M4 门禁验证）
- UI 风格：DESIGN.md 币安风格（深黑底 + 币安黄 + 涨绿跌红）
- 数据：一期全免费源（AkShare + BaoStock + exchange_calendars + Chinese-FinBERT + DeepSeek）
