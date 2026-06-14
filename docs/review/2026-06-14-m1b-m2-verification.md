# M-1b/M2 xtquant 通道 + 模拟盘主线 验证报告

> 日期：2026-06-14　分支：`feat/m1b-m2-xtquant`
> 对照：设计 v0.5 §4.1.1（行情网关）、§4.6（执行层）、§4.6.2（状态机/on_fill）、§4.6.4（对账）、§6（DuckDB 交接）、§11 M-1b/M2

---

## 0. 关键约束（诚实声明）

**xtquant 是 Windows-only**（随 QMT 终端分发，macOS pip 不可装）。本机 macOS 无法运行真实 xtquant/QMT。故：
- **代码层全做**：QmtGateway/QmtBroker 适配器（xtquant lazy import）+ 全部周边可移植机制 + mock 单测
- **live xtquant 验证须 Windows + QMT 客户端登录态**（用提供的 QMT 账户/密码登录客户端后，本代码即可连）

## 1. 测试证据

| 套件 | 结果 |
|---|---|
| 后端 `pytest tests/ -m "not slow and not network"` | **449 passed, 1 xfailed, 6 deselected** |
| M-1b/M2 验收（mock） | 10/10 绿，确定性（seed=2024） |

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

---

## 3. Windows live 验证清单（待用户在 Windows + QMT 执行）

下列项本机仅 mock，真实值须 Windows 实测：
1. xtquant 订阅频率/回调线程时序（ThreadBridge 已就位，验真实回调线程）
2. 真实下单延迟绝对值（mock 下 <100ms，live 阈值实测）
3. xttrader 断线指数退避重连（当前靠析构+新建实例；可补显式 reconnect API）
4. xt API 签名回归（order_stock/cancel_order_stock 字段名，真实样本校验）
5. 连续 20 交易日实盘对账差异 <0.1%（§11 M2 真值）

**操作**：Windows 装 QMT 终端 → 用 QMT 账户/密码登录 → `.env` 配置 → `python -m pytest tests/quant/test_m1b_m2_acceptance.py`（移除 mock，接真实 xtquant）→ 跑 live。

---

## 4. 结论

**M-1b/M2 代码层全部完成并通过 mock 验收**（449 测试绿）：行情网关（PIT/线程桥/去重/背压/QmtGateway）+ 执行层（Broker/状态机/订单簿/SimBrokerLive/QmtBroker per-account）+ 对账 + DuckDB 交接 + M-1b 探测 mock + M2 闭环 mock。**live xtquant 验证待 Windows + QMT 登录态**（清单见 §3）。至此 M0→M1.5+M3+M-1b/M2 的本地可建部分全部就位，系统具备在 Windows 上接 QMT 跑模拟盘的完整代码基础。
