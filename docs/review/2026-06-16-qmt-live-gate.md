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
| 实时订阅回调 | BLOCKED | 代码层兼容真实回调形态 `{stock: [data, ...]}` 与 `{stock: data}`；现场 QMT 复测 `subscribe_quote`、`subscribe_whole_quote`、项目 `QmtGateway` tick 订阅 60 秒均未收到回调 |
| full tick 快照 | BLOCKED | `get_full_tick=PASS keys=0`，未返回标的实时 tick |
| 分钟行情读取 | PASS | `get_market_data_ex_1m=PASS keys=1` |
| 模拟盘下单/撤单 | PASS | `600000.SH` 100 股、限价 1.00 买入委托两次均返回正订单号；撤单返回 0；订单列表最终 `order_status=54`、`traded_volume=0`；成交列表匹配数 0 |
| 真实实盘下单/撤单 | NOT RUN | 当前为模拟盘门禁；未执行真实资金交易动作 |

## 放行判断

可放行：

- 本机 QMT/xtquant 安装与本地行情服务可用。
- 只读历史/分钟行情可读。
- trader 对两个指定账号均可构造并查询持仓、委托、成交列表。
- 项目 QMT 适配层测试通过。
- 模拟盘最小下单/撤单门禁通过，且没有成交。

不可放行：

- M4 影子模式/小资金实盘仍不可放行。
- 真实资金下单、撤单、下单延迟、撤单延迟、断线恢复、真实成交回报对账仍未验证。
- 现场实时订阅仍未收到回调，不能证明当前 QMT 终端/行情权限满足实盘策略驱动要求。

## 下一步

1. 在 QMT 客户端确认实时行情/全推权限与 Python 回调开关，复跑 `subscribe_quote`、`subscribe_whole_quote` 与项目 `QmtGateway` tick 回调探测。
2. 复测断线恢复：交易侧 `userdata` 路径重连、订单列表回放、重复 `client_order_id` 防重。
3. 只有实时回调和断线恢复通过后，才进入真实资金下单/撤单门禁；真实交易动作必须由用户明确授权，并指定账号、标的、数量、价格和撤单策略。
