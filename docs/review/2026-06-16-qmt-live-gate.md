# QMT Live 门禁记录（2026-06-16）

## 结论

本次在用户已打开并登录 QMT 客户端后执行 live 门禁探测。所有操作均为只读，未调用下单或撤单接口。

当前结论：QMT 只读连接门禁部分通过，但不能放行 M4 实盘门禁。2026-06-16 下午复核后，实时行情阻断点进一步收敛为 MiniQuote 行情权限/用户态授权未向 `58610` 下发实时数据；不是项目侧订阅代码、单标的写法或本机端口未启动。

2026-06-16 方案重设计后，QMT 不再被设计为唯一行情前置条件：QMT 保留为交易执行主通道；行情侧新增健康状态与多源仲裁层。若 QMT `get_full_tick` 与最近 bar 均为空，系统会把 QMT 行情判定为 `BLOCKED/UNAVAILABLE`，而不是把订阅任务号当作成功。

## 环境

- `QMT_USERDATA_PATH`: 行情只读可用路径为 `D:\迅投极速交易终端 睿智融科版\userdata_mini`；交易侧正确路径为 `D:\迅投极速交易终端 睿智融科版\userdata`
- `QMT_ACCOUNT`: 已由用户提供并先后测试两个资金账号，记录脱敏为 `********2764`、`***0707`
- 探测标的：`600519.SH`

## 结果

| 门禁项 | 状态 | 证据 |
|---|---|---|
| xtquant import | PASS | `.venv\Scripts\python.exe -m probes.qmt_live` |
| QMT 行情服务连接 | PASS | `xtdata` 连接到本地服务 `127.0.0.1:58610` |
| 日线行情读取 | PASS | `market_data_read=PASS` |
| trader 只读握手 | PASS | `trader_readonly_handshake=PASS` |
| QMT 适配层自动测试 | PASS | `tests\quant\test_execution_qmt_broker.py tests\quant\test_gateway_qmt.py tests\quant\test_m1b_m2_acceptance.py tests\probes\test_qmt_live.py -q` -> `39 passed` |
| 原生 trader 连接 | PASS | `trader_connect=PASS` |
| 持仓查询 | PASS | `positions=PASS count=0` |
| 当日委托查询 | PASS | `orders=PASS count=0` |
| 当日成交查询 | PASS | `trades=PASS count=0` |
| 资产查询 | PASS | 使用交易侧 `userdata` 路径后返回 `XtAsset` 对象 |
| 实时订阅 API | PARTIAL | 代码层已修正：周期订阅逐标的调用 `subscribe_quote(stock_code, ...)`；tick 实时订阅优先 `subscribe_whole_quote(code_list, ...)`；启动 `xtdata.run()` 后台循环 |
| 项目侧订阅兜底 | PASS | `QmtGateway` 已增加只读轮询兜底：回调未推送时先读 `get_full_tick`，空结果再读 `get_market_data_ex` 最近一根 bar；兼容真实 `{symbol: DataFrame}` 返回并显式传入 `path\datadir` |
| 实时订阅回调 | BLOCKED | 现场 QMT 复测 `subscribe_quote`、`subscribe_whole_quote`、项目 `QmtGateway` tick 订阅 60 秒均未收到 Python 回调 |
| full tick 快照 | BLOCKED | `get_full_tick=PASS keys=0`，未返回标的实时 tick |
| 分钟行情有效数据 | BLOCKED | API 可调用，但 `600000.SH` 的 `get_market_data_ex(period="1m", count=1)` 返回空 DataFrame，项目侧轮询兜底因此也无可桥接 bar |
| 终端侧行情进程 | BLOCKED | 主终端 `XtItClient.exe` 监听 `58600` 且日志可见 `SH_600000` 行情 push；xtdata 默认连接的 MiniQuote `58610` 可连接但 `get_full_tick` 为空。手工 `miniquote.exe linkMiniQuoteHide` 日志出现 `server only support xt user mode`/空用户名；改由 `XtMiniQmt.exe` 拉起后仍未让 Python API 获得有效 tick/K 线 |
| 模拟盘下单/撤单 | PASS | `600000.SH` 100 股、限价 1.00 买入委托两次均返回正订单号；撤单返回 0；订单列表最终 `order_status=54`、`traded_volume=0`；成交列表匹配数 0 |
| 真实实盘下单/撤单 | NOT RUN | 当前为模拟盘门禁；未执行真实资金交易动作 |

## 2026-06-16 下午复核

- “同时在线数超出限制”由现场同时残留主 QMT、MiniQMT、MiniQuote、MiniBroker 触发。清理重复进程并等待后，重新启动主终端，主终端可生成 `bin.x64\linkQmt`，并托管拉起 `miniquote.exe "linkMiniQuoteHide"`。
- 当前保留主终端托管模式，不再反复重启 MiniQMT，避免再次触发在线数门禁。
- `58600` 为主终端接口，连接后调用 xtdata 行情函数返回 `ErrorID=200005 未找到处理函数`，不能作为实时行情入口。
- `58610` 为 MiniQuote xtdata 行情接口，连接成功且 `get_data_dir()` 指向 QMT `userdata_mini\datadir`。
- `58610` 最新复测：`get_full_tick(["600000.SH","000001.SZ","510300.SH"]) -> {}`；`subscribe_quote("600000.SH", period="tick")` 10 秒超时；`subscribe_whole_quote(["SH","SZ"])` 返回任务号 `1/2`，等待 60 秒无回调。
- MiniQuote 到多个行情服务器存在 Established TCP 连接，`xtquoterconfig.xml` 中普通行情服务器 `username=""`，日志仍出现整市场 `No Data Push`/订阅超时。现象更符合账号或终端模式未获得 MiniQMT/Python API 实时行情授权，而非本地服务未启动。
- 主终端交易侧在线，模拟资金、持仓/资金查询与推送持续正常；阻断范围限定在 MiniQuote 实时行情向 Python API 暴露数据。

## 2026-06-16 方案重设计

- 新增行情健康契约：`GatewayHealth(status, source, quality, reason, checked_at)`。`PASS` 可作为主源；`DEGRADED` 只能降级使用；`BLOCKED` 不可用于当前策略频率。
- `QmtGateway.health(symbols, freq)` 的判定规则：
  - tick：`get_full_tick` 非空 -> `PASS/REALTIME`。
  - tick 空但最近 1m bar 非空 -> `DEGRADED/DELAYED`。
  - tick 与最近 bar 均空 -> `BLOCKED/UNAVAILABLE`。
  - 非 tick：最近 `market_data_ex` 非空才可用。
- 新增 `FailoverMarketDataGateway`：按健康状态选择行情源，优先 `PASS`，其次 `DEGRADED`；全部 `BLOCKED` 时抛 `MarketDataUnavailable`，上层必须阻断 live 策略，不能 silent success。
- 新增备用快照源：`SnapshotMarketDataGateway` 可接收标准 DataFrame 作为延迟/缓存行情；`AkShareDailySnapshotGateway` 可把 AkShare 日线 OHLCV 拉取结果转换为标准快照。该路径只用于历史/盘后/影子验证，不作为实时 tick 放行依据。
- `probes.qmt_live` 新增 `market_data_health` 检查，现场复测结果为：`xtquant_import=PASS`、`market_data_read=PASS`、`trader_readonly_handshake=PASS`、`market_data_health=BLOCKED`。交易侧与实时行情侧已能分开判定。
- network 门禁单独复测：BaoStock、NLP 模型、LLM 连通、M5b/Mining/Actor 真实 LLM 流程均通过；AkShare 日线真实网络项因本机代理 `127.0.0.1:7897` 到东方财富连接断开失败。该失败影响 AkShare 备用日线源的现场拉取，不影响 QMT 交易侧判定。
- `probes.network_gate` 已新增外部服务健康汇总：当前 overall `PASS`，其中 required `baostock_daily`/`llm_api` 通过，optional `akshare_daily` 因代理到东方财富失败为 `BLOCKED`。
- `quant.execution.live_readiness` 已新增执行层 live 硬挡板：自动 live 必须同时满足行情 `PASS/REALTIME` 与 broker 只读账户检查；`DEGRADED/DELAYED`、`PASS/HISTORICAL`、无 `health()` 契约或 broker 检查失败都会阻断。
- `probes.project_gate` 已新增项目级门禁：统一汇总 QMT 只读交易握手、QMT 实时行情健康、执行层 live readiness 与必需 network gate。当前现场预期输出为整体 `BLOCKED`，核心原因是 `qmt_market_data_health=BLOCKED` 且 `live_readiness=BLOCKED`；即使 BaoStock/LLM 必需网络项通过，也不能放行盘中 live 策略。
- 新架构边界：QMT 交易执行与 QMT 行情解耦。交易侧 `QmtBroker` 可继续做模拟盘/只读/撤单验证；策略 live 放行必须额外依赖行情源健康，不能因为交易侧在线就默认行情可用。

## 放行判断

可放行：

- 本机 QMT/xtquant 安装与本地行情服务可用。
- 只读历史/分钟行情可读。
- trader 对两个指定账号均可构造并查询持仓、委托、成交列表。
- 项目 QMT 适配层测试通过。
- 模拟盘最小下单/撤单门禁通过，且没有成交。
- 代码层已经能在 QMT Python API 提供有效 `get_full_tick` 或最近 bar 时绕过“订阅注册成功但不推回调”的问题。

不可放行：

- M4 影子模式/小资金实盘仍不可放行。
- 真实资金下单、撤单、下单延迟、撤单延迟、断线恢复、真实成交回报对账仍未验证。
- 现场实时订阅仍未收到 Python 回调，且 MiniQuote `58610` 未向 Python API 暴露有效 tick/分钟 bar；不能证明当前 QMT 终端/行情权限满足实盘策略驱动要求。
- 在新方案下，当前现场 QMT 行情会被 `QmtGateway.health(["600000.SH"], "tick")` 判定为 `BLOCKED/UNAVAILABLE`。若没有备用实时行情源，策略 live 必须阻断；若接入备用源，也只能按备用源质量进入影子/模拟或人工确认模式。
- AkShare 日线备用源可补历史/盘后快照，但不能替代 QMT/券商实时行情。当前仍不能放行盘中自动实盘策略。

## 统一门禁入口

本地回归与外部依赖分三层运行：

- 后端非 network 回归：`.venv\Scripts\python.exe -m pytest tests\quant -m "not network" -q`，用于证明代码逻辑、接口契约和本地模拟链路没有回归。
- 外部网络门禁：`.venv\Scripts\python.exe -m probes.network_gate`，用于证明必需外部服务可连通；AkShare 日线备用源当前是 optional。
- 项目级门禁：`.venv\Scripts\python.exe -m probes.project_gate`，用于给出最终 PASS/BLOCKED。当前只要 QMT 实时行情健康仍为 `BLOCKED`，项目级门禁就必须阻断盘中 live。
- 完整统一门禁：`.venv\Scripts\python.exe -m probes.full_gate`，依次执行 probes 非 network、quant 非 network、`git diff --check` 和 project gate。该命令用于交付前的一键状态判断；任一子命令超时会被记录为结构化 `BLOCKED`。

2026-06-16 现场运行 `probes.project_gate` 的结果：整体 `status=BLOCKED`；`qmt_trader=PASS`、`qmt_market_data_health=BLOCKED`、`live_readiness=BLOCKED`；`baostock_daily` 与 `llm_api` required 项为 `PASS`；`akshare_daily` optional 项因本机代理到东方财富失败为 `BLOCKED`。

2026-06-16 现场运行 `probes.full_gate` 的结果：probes 非 network PASS（28 passed, 3 deselected, 1 xfailed）、quant 非 network PASS（681 passed, 4 deselected, 21 warnings）、`git diff --check` PASS（仅 CRLF 提示）；最终整体 `status=BLOCKED`，原因是 project gate 中 QMT 实时行情健康与 live readiness 仍为 `BLOCKED`。

## 下一步

1. 在 QMT 客户端确认 MiniQMT/Python API 行情权限与启动方式：需要让 `58610` 侧 MiniQuote 使用登录用户态并能返回 `get_full_tick(["600000.SH"])` 或非空 `get_market_data_ex(..., period="1m")`。
2. 复测断线恢复：交易侧 `userdata` 路径重连、订单列表回放、重复 `client_order_id` 防重。
3. 只有实时回调和断线恢复通过后，才进入真实资金下单/撤单门禁；真实交易动作必须由用户明确授权，并指定账号、标的、数量、价格和撤单策略。
