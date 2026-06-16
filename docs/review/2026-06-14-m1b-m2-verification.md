# M-1b/M2 xtquant 通道 + 模拟盘主线 验证报告

> 日期：2026-06-14　分支：`feat/m1b-m2-xtquant`
> 对照：设计 v0.5 §4.1.1（行情网关）、§4.6（执行层）、§4.6.2（状态机/on_fill）、§4.6.4（对账）、§6（DuckDB 交接）、§11 M-1b/M2

---

## 0. 关键约束（诚实声明）

**xtquant 是 Windows/QMT 客户端通道**（依赖本机 QMT 投研版或极简版服务）。当前已在 Windows 环境安装 `xtquant` Python 包并完成 import/API 签名检查；真实 live 探测仍依赖 QMT 客户端服务在线。

- **代码层全做**：QmtGateway/QmtBroker 适配器（xtquant lazy import）+ 全部周边可移植机制 + mock 单测
- **Windows 包验证已推进**：`xtquant`、`xtdata`、`xttrader` import 通过，`subscribe_quote`、`get_market_data_ex`、`XtQuantTrader` 签名已检查
- **live xtquant 只读验证已通过**：QMT 客户端在线后，只读行情读取与 trader 只读握手均 PASS；未触发下单/撤单

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `.venv\Scripts\python.exe -m pytest tests\quant -m "not network" -q` | **648 passed, 4 deselected, 21 warnings** |
| M-1b/M2 验收（mock） | 10/10 绿，确定性（seed=2024） |
| P1 连续 20 交易日模拟盘 | **1/1 绿**：20 日、2 账户、5 主板标的，StrategyRunner→SimBrokerLive→on_fill→日终 reconcile |
| Windows QMT 安全 probe 单测 | **5 passed** |
| Windows QMT live probe | **pass**：Python 包可导入，行情只读读取 PASS，trader 只读握手 PASS |
| QMT/M2 mock + adapter 回归 | **39 passed** |

---

## 2. 组件 vs 设计

### §4.1.1 行情网关
- ✅ MarketDataGateway Protocol（subscribe/history/**bar_at PIT 安全**）
- ✅ ThreadBridge（xtquant 内部线程 → asyncio `call_soon_threadsafe`，真线程测试验证）
- ✅ BarDedup（唯一键 symbol/freq/ts，FIFO 驱逐）
- ✅ Backpressure（队列深度阈值，3 策略 drop_oldest/drop_newest/coalesce + 告警）
- ✅ QmtGateway（xtquant lazy import，无→RuntimeError('Windows-only')，回调经 ThreadBridge 桥接）

### §4.6 执行层
- ✅ Broker Protocol（place/cancel/status/positions/account/on_fill/is_synchronous）
- ✅ OrderStatus 状态机（PENDING→SUBMITTED→PARTIAL_FILLED→FILLED / CANCELLED/REJECTED，合法图+幂等）
- ✅ OrderBook（client_order_id 去重防断线重复，order_event 重放恢复）
- ✅ SimBrokerLive（is_synchronous=True，place 立即撮合 + **on_fill 统一入口**同步/异步双路径，复用 M1 撮合）
- ✅ QmtBroker（per-account 隔离，xtquant lazy，is_synchronous=False，xt 状态映射，on_fill 桥接）

### §4.6.4 对账
- ✅ reconcile（四类 mismatch：local/broker 缺失/qty/status，diff_rate，threshold<0.1%，audit_event 落库）

### §6 DuckDB 交接
- ✅ DuckdbHandoff + WriteLease（lockfile 跨进程写权，过期接管，holder 防误删，盘中→盘后交接）

### §11 M-1b 探测（mock）
- ✅ 订阅线程桥接 / 下单延迟（mock 计时）/ 崩溃重连（析构+新建实例语义）

### §11 M2 集成（mock 行情）
- ✅ 信号→因子→策略→SimBrokerLive→on_fill→持仓闭环；对账 diff<0.1%；多账户隔离；去重背压；交接；Windows-only 标注
- ✅ 连续 20 交易日模拟盘验收：固定 seed 合成行情，20 日 × 2 账户 × 5 主板标的，使用 `StrategyRunner.on_fills` 派发成交，日终 reconcile 全部 `diff_rate < 0.1%`，多账户订单/持仓隔离正确。

---

## 3. Windows live 验证清单

已新增安全探测入口：

```powershell
.venv\Scripts\python.exe -m probes.qmt_live
```

该入口只做只读行情和只读 trader 握手，不调用下单/撤单 API，不输出密码/token。当前阶段结果：

1. `xtquant_import=PASS`
2. `market_data_read=PASS`
3. `trader_readonly_handshake=PASS`

同步修正：

- `QmtBroker` 真实环境使用 `xttype.StockAccount(account_id)` 构造账户对象，不再依赖 fake 测试里的 `get_stock_account`。
- `QmtBroker.status()` 兼容真实 `query_stock_order(account, order_id)`。
- 真实只读 smoke：broker 构造、账户查询、持仓查询均未抛异常；不调用 `order_stock` 或撤单 API。

下列项仍需 QMT 客户端在线后继续实测：
1. xtquant 订阅频率/回调线程时序（ThreadBridge 已就位，验真实回调线程）
2. 真实下单延迟绝对值（mock 下 <100ms，live 阈值实测）
3. xttrader 断线指数退避重连（当前靠析构+新建实例；可补显式 reconnect API）
4. xt API 签名回归（order_stock/cancel_order_stock 字段名，真实样本校验）
5. 连续 20 交易日实盘对账差异 <0.1%（模拟盘已过；真实 QMT/券商回报仍需 live 真值）

**操作**：Windows 打开并登录 QMT 终端 → `.env` 配置必要 QMT 路径与账户标识 → 先运行只读 probe → 再运行 `python -m pytest tests/quant/test_m1b_m2_acceptance.py`（移除 mock，接真实 xtquant）→ 跑 live。

---

## 4. 结论

**M-1b/M2 代码层全部完成并通过 mock/模拟盘验收**：行情网关（PIT/线程桥/去重/背压/QmtGateway）+ 执行层（Broker/状态机/订单簿/SimBrokerLive/QmtBroker per-account）+ 对账 + DuckDB 交接 + M-1b 探测 mock + M2 闭环 mock + 连续 20 交易日模拟盘验收。Windows 阶段已确认 `xtquant` Python 包、核心模块、只读行情读取、trader 只读握手与 broker 只读查询路径可用。仍未做真实下单/撤单/断线恢复/连续 20 交易日真实 QMT 回报对账；这些必须在 live/实盘灰度计划下单独执行。
