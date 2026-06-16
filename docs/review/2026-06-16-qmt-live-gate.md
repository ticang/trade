# QMT Live 门禁记录（2026-06-16）

## 结论

本次在用户已打开并登录 QMT 客户端后执行 live 门禁探测。所有操作均为只读，未调用下单或撤单接口。

当前结论：QMT 只读连接门禁部分通过，但不能放行 M4 实盘门禁。

## 环境

- `QMT_USERDATA_PATH`: `D:\迅投极速交易终端 睿智融科版\userdata_mini`
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
| 资产查询 | BLOCKED | 两个资金账号接口均不报错，但返回空对象：`asset=PASS empty` / `broker_account=PASS empty`，不能作为资金账户已完整可读的证据 |
| 实时订阅 API | PARTIAL | `subscribe_quote=PASS`、`unsubscribe_quote=PASS` |
| 实时订阅回调 | BLOCKED | 20 秒、带 `xtdata.run()` 30 秒两次探测均 `callback_received=BLOCKED count=0` |
| full tick 快照 | BLOCKED | `get_full_tick=PASS keys=0`，未返回标的实时 tick |
| 分钟行情读取 | PASS | `get_market_data_ex_1m=PASS keys=1` |
| 真实下单/撤单 | NOT RUN | 未获明确授权，且资产/实时回调门禁未通过，不执行真实交易动作 |

## 放行判断

可放行：

- 本机 QMT/xtquant 安装与本地行情服务可用。
- 只读历史/分钟行情可读。
- trader 对两个指定账号均可构造并查询持仓、委托、成交列表。
- 项目 QMT 适配层测试通过。

不可放行：

- M4 影子模式/小资金实盘仍不可放行。
- 真实下单、撤单、下单延迟、撤单延迟、断线恢复、真实成交回报对账仍未验证。
- 两个资金账号均复现资产查询返回空对象，不能证明资金账户资产侧已完整可读。
- 实时订阅未收到回调，不能证明 QMT 回调线程桥接满足实盘策略驱动要求。

## 下一步

1. 在 QMT 客户端确认交易模块和资金账号资产页可正常显示，再复跑资产只读查询。
2. 在交易时段确认行情订阅权限/全推权限，复跑 `subscribe_quote` 回调探测。
3. 只有资产查询和实时回调均通过后，才进入真实下单/撤单门禁；真实交易动作必须由用户明确授权，并指定账号、标的、数量、价格和撤单策略。
