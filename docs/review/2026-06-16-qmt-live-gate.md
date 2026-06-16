# QMT Live 门禁记录（2026-06-16）

## 结论

本次在用户已打开并登录 QMT 客户端后执行 live 门禁探测。所有操作均为只读，未调用下单或撤单接口。

当前结论：QMT 只读连接门禁部分通过，但不能放行 M4 实盘门禁。

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

## 下一步

1. 在 QMT 客户端确认 MiniQMT/Python API 行情权限与启动方式：需要让 `58610` 侧 MiniQuote 使用登录用户态并能返回 `get_full_tick(["600000.SH"])` 或非空 `get_market_data_ex(..., period="1m")`。
2. 复测断线恢复：交易侧 `userdata` 路径重连、订单列表回放、重复 `client_order_id` 防重。
3. 只有实时回调和断线恢复通过后，才进入真实资金下单/撤单门禁；真实交易动作必须由用户明确授权，并指定账号、标的、数量、价格和撤单策略。
