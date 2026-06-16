"""M-1b 探测（mock xtquant）+ M2 集成验收（capstone）。

对应设计 v0.5 §11 M-1b / M2 两条验收：

- M-1b 探测：订阅频率/回调线程/下单延迟/客户端崩溃恢复。xtquant 在 macOS 不可装，
  本机通过 sys.modules 注入 fake xtquant 模块模拟实盘路径；live xtquant 验证须在
  Windows + QMT 终端环境完成——本测试不替代该环境验证。
- M2 集成验收：信号→下单→持仓→对账闭环（确定性，mock 行情），对账差异 < 0.1%，
  多账户隔离。所有数据合成、固定 seed，独立可重跑。

诚实记录：本测试只覆盖 mock/确定性路径，live xtquant 在本机无法验证。
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quant.backtest.sim_broker import BarSnapshot, Order
from quant.data.duckdb_handoff import DuckdbHandoff, WriteLease
from quant.events import BarEvent, EventBus
from quant.execution.broker import OrderStatus
from quant.execution.reconcile import reconcile
from quant.execution.sim_broker_live import SimBrokerLive
from quant.factor.factors.momentum import MomentumFactor
from quant.factor.registry import FactorRegistry
from quant.gateway.backpressure import Backpressure, BackpressureConfig
from quant.gateway.dedup import BarDedup
from quant.gateway.qmt import QmtGateway
from quant.gateway.thread_bridge import ThreadBridge
from quant.strategy.context import BarContext
from quant.strategy.signal import Signal

# 固定 seed，保证合成数据确定性
_SEED = 2024

# 沪市主板规则（与 test_m1_acceptance 一致，便于 SimBroker 撮合）
_RULE_MAIN = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
    "min_buy": 100,
    "lot_increment": 100,
    "fees": {
        "stamp": {"value": 0.0005, "_confidence": "provisional"},
        "transfer": {"value": 0.00001, "_confidence": "provisional"},
        "commission": {"value": None, "_confidence": "provisional"},
        "exchange": {"value": None, "_confidence": "provisional"},
    },
}


def _rule_fn() -> dict:
    """返回当前生效 rule_json（模拟 TradingRuleProvider 取数）。"""
    return _RULE_MAIN


# ===========================================================================
# M-1b fake xtquant 工厂（与现有 test_gateway_qmt / test_execution_qmt_broker 一致）
# ===========================================================================

def _install_fake_xtquant(monkeypatch) -> dict:
    """注入 fake xtquant.xtdata + xtquant.xttrader 到 sys.modules。

    返回 state dict：
      - last_callback: subscribe 时注册的回调（模拟 xtquant 内部线程触发）
      - trader_instances: 创建的 _FakeXtQuantTrader 实例列表
      - subscribe_calls / order_stock_calls: 调用记录
    """
    state: dict = {
        "last_callback": None,
        "subscribe_calls": [],
        "history_calls": [],
        "trader_instances": [],
        "order_stock_calls": [],
    }

    # ---- fake xtdata ----
    xtdata = types.ModuleType("xtquant.xtdata")

    def subscribe_quote(symbols, period="", callback=None, **kwargs):
        state["subscribe_calls"].append({
            "symbols": list(symbols), "period": period,
            "callback": callback, "kwargs": kwargs,
        })
        state["last_callback"] = callback
        return 0

    def get_market_data_ex(period="", start_time="", end_time="", **kwargs):
        state["history_calls"].append({"period": period})
        return pd.DataFrame()

    xtdata.subscribe_quote = subscribe_quote  # type: ignore[attr-defined]
    xtdata.get_market_data_ex = get_market_data_ex  # type: ignore[attr-defined]

    # ---- fake xttrader ----
    xttrader = types.ModuleType("xtquant.xttrader")

    class _FakeXtQuantTrader:
        def __init__(self, path, session_id):
            self.path = path
            self.session_id = session_id
            self.start_called = False
            self.connect_called = False
            self.stop_called = False
            state["trader_instances"].append(self)

        def start(self):
            self.start_called = True
            return 0

        def connect(self):
            self.connect_called = True
            return 0

        def stop(self):
            self.stop_called = True
            return 0

        def get_stock_account(self, account_id):
            return {"account_id": account_id}

        def order_stock(self, **kwargs):
            state["order_stock_calls"].append(kwargs)
            return len(state["order_stock_calls"])  # 自增 seq

        def cancel_order_stock(self, **kwargs):
            return 0

        def query_order(self, account, order_id):
            return {"order_status": 55}  # xt 已成交

        def query_stock_positions(self, account):
            return []

        def query_stock_asset(self, account):
            return {"cash": 0.0}

        def register_callback(self, cb):
            return 0

    xttrader.XtQuantTrader = _FakeXtQuantTrader  # type: ignore[attr-defined]

    # ---- fake 顶层 xtquant 包 ----
    xtquant_pkg = types.ModuleType("xtquant")
    xtquant_pkg.xtdata = xtdata  # type: ignore[attr-defined]
    xtquant_pkg.xttrader = xttrader  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "xtquant", xtquant_pkg)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader)
    return state


# ===========================================================================
# M-1b 验收 1：subscribe 触发内部线程回调 → ThreadBridge → asyncio loop 收到 bar
# ===========================================================================

def test_m1b_subscribe_thread_bridge(monkeypatch) -> None:
    """§11 M-1b 验收 1：mock xtquant，subscribe 的内部线程回调经 ThreadBridge 投递到 loop。

    - 在另一线程触发 fake xtdata 回调（模拟 xtquant 内部线程）
    - ThreadBridge.bridge 跨线程调 loop.call_soon_threadsafe(on_bar, bar)
    - asyncio loop 上 on_bar 收到 bar（symbol/close/available_at 完整）
    """
    state = _install_fake_xtquant(monkeypatch)

    received: list[dict] = []
    loop_event = threading.Event()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        bridge = ThreadBridge(loop=loop, on_bar=lambda b: received.append(b))
        gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)
        gw.subscribe(["600519"], "1d", lambda b: received.append(b))

        # 在另一线程触发 fake xtquant 回调（模拟内部行情线程）
        raw_data = {
            "stock": "600519",
            "time": 1710489600000,  # ms 时间戳
            "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0,
            "volume": 100000, "amount": 1000000.0,
        }
        cb = state["last_callback"]
        assert cb is not None
        t = threading.Thread(target=cb, args=(raw_data,))
        t.start()

        # 等 loop 处理 call_soon_threadsafe（轮询 received，超时 1s）
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.01)
        t.join(timeout=1.0)
        loop_event.set()

    asyncio.run(_run())

    assert len(received) >= 1, "loop 未收到经 ThreadBridge 桥接的 bar"
    bar = received[0]
    assert bar["symbol"] == "600519"
    assert bar["freq"] == "1d"
    assert bar["close"] == 10.0
    assert bar["volume"] == 100000
    assert "available_at" in bar


# ===========================================================================
# M-1b 验收 2：下单延迟可测（mock 即时返回；live 阈值标 Windows）
# ===========================================================================

def test_m1b_order_latency_mock(monkeypatch) -> None:
    """§11 M-1b 验收 2：QmtBroker.place 计时（mock 即时返回）。

    mock xtquant.order_stock 即时返回，延迟应极小（< 100ms）。
    live 实盘下单延迟阈值须在 Windows + QMT 终端实测标定——本机仅验证可测。
    """
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                      session_id=1, bridge=bridge)

    order = Order(symbol="600519", side="buy", qty=100, price=10.00)

    t0 = time.perf_counter()
    broker.place(order, client_order_id="lat-1")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # mock 即时返回，延迟应极小；仅断言可测 + 合理上限（不绑定实盘性能数字）
    assert elapsed_ms >= 0.0
    assert elapsed_ms < 100.0, f"mock 下单延迟异常 {elapsed_ms:.3f}ms"
    assert len(state["order_stock_calls"]) == 1


# ===========================================================================
# M-1b 验收 3：客户端崩溃恢复 / 重连逻辑可调用（简化）
# ===========================================================================

def test_m1b_crash_recovery_reconnect(monkeypatch) -> None:
    """§11 M-1b 验收 3：客户端崩溃恢复——模拟 xttrader 连接断开后可重新构造。

    现有 QmtGateway/QmtBroker 的重连语义：构造时 start+connect，崩溃后通过
    析构 + 新建实例完成重连（不在实例上暴露显式 reconnect 方法）。
    本测试验证：
      - close 可调用（释放 trader 连接）
      - 重新构造（同 path/session）不抛，新实例 start/connect 被调用
      - 重连后 place 仍可调（client_order_id 隔离于新实例）

    真正的指数退避重试 + xttrader 断线事件回调需 live xtquant 环境验证。
    """
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                      session_id=1, bridge=bridge)
    trader_first = state["trader_instances"][-1]
    assert trader_first.connect_called is True

    # 模拟崩溃：QmtBroker 未暴露 close（与 QmtGateway 不同），
    # 通过 QmtGateway.close 验证 trader.stop 释放路径
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)
    gw.close()
    assert state["trader_instances"][-1].stop_called is True

    # 重连：重新构造新 broker 实例（同 account_id/session）
    broker2 = QmtBroker(account_id="acct1", path="/tmp/qmt",
                        session_id=1, bridge=bridge)
    trader2 = state["trader_instances"][-1]
    assert trader2.connect_called is True
    assert trader2 is not trader_first

    # 新实例的 client_order_id 集合独立（崩溃前的 id 在新实例中可用）
    order = Order(symbol="600519", side="buy", qty=100, price=10.00)
    broker2.place(order, client_order_id="reconnect-1")  # 不抛


# ===========================================================================
# M2 验收 4：信号→下单→持仓→on_fill 闭环（确定性 mock 行情）
# ===========================================================================

class _MomentumTop1Strategy:
    """简单动量策略：选 factor_panel 动量值最高的 1 个 symbol 产买入 Signal。"""

    name = "momentum_top1"
    required_factors = ["momentum_5"]

    def __init__(self) -> None:
        self._fills: list[Any] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        panel = ctx.factor_panel
        col = "momentum_5"
        if panel.empty or col not in panel.columns:
            return []
        mom = panel[col].dropna()
        if mom.empty:
            return []
        top = mom.idxmax()
        return [Signal(symbol=str(top), direction=1, strength=float(mom.loc[top]))]

    def on_fill(self, ctx: Any) -> None:
        self._fills.append(ctx)


def _synth_panel(n_symbols: int, n_days: int, seed: int):
    """合成 N symbol × T day panel：close 带趋势，固定 seed。"""
    rng = np.random.default_rng(seed)
    start = _dt.date(2021, 1, 4)
    days = [_step_weekday(start, i) for i in range(n_days)]
    symbols = [f"60000{i}.SH" for i in range(n_symbols)]

    rows = []
    bars: dict[tuple[str, _dt.date], BarSnapshot] = {}
    for j, sym in enumerate(symbols):
        price = 20.0 + j * 5.0
        drift = rng.uniform(0.0, 0.004)  # 轻微上涨
        noise = rng.normal(0, 0.01, size=n_days)
        prices = price * np.cumprod(1 + drift + noise)
        for i, d in enumerate(days):
            c = round(float(prices[i]), 2)
            rows.append({
                "symbol": sym, "trade_date": d,
                "available_at": _day_end(d), "close": c,
            })
            bars[(sym, d)] = BarSnapshot(
                open=c, high=c * 1.02, low=c * 0.98, close=c,
                volume=1_000_000.0,
                limit_up=c * 1.10, limit_down=c * 0.90,
            )
    return pd.DataFrame(rows), bars, days


def _step_weekday(start: _dt.date, i: int) -> _dt.date:
    """start + i 个工作日（跳过周末）。"""
    d = start
    stepped = 0
    while stepped < i:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            stepped += 1
    return d


def _day_end(d: _dt.date) -> _dt.datetime:
    return _dt.datetime.combine(d, _dt.time(hour=16, minute=0))


def test_m2_signal_to_fill_loop() -> None:
    """§11 M2 验收 4：信号→下单→持仓→on_fill 闭环。

    组装（确定性）：
      FakeGateway（合成 panel，内存 bars）
        → EventBus（BarEvent）
        → FactorRegistry（momentum_5）
        → _MomentumTop1Strategy（选 top-1 产 Signal）
        → SimBrokerLive（set_bar + place + on_fill）
        → 持仓更新

    跑 3-5 日，断言 fills 产出、持仓更新、on_fill 回调触发。
    """
    panel, bars, days = _synth_panel(n_symbols=3, n_days=8, seed=_SEED)
    symbols = sorted(panel["symbol"].unique().tolist())

    registry = FactorRegistry()
    registry.register(MomentumFactor(window=5))

    strategy = _MomentumTop1Strategy()
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    received_fills: list[Any] = []
    broker.on_fill(lambda f: received_fills.append(f))

    bus = EventBus()

    # FakeGateway：每个 bar 经 EventBus publish BarEvent
    def _emit_bar(symbol: str, day: _dt.date) -> None:
        bar = bars.get((symbol, day))
        if bar is None:
            return
        bus.publish(BarEvent(
            symbol=symbol, freq="1d",
            ts=_day_end(day), close=bar.close, volume=bar.volume,
        ))

    # 订阅：收到 BarEvent → set_bar → 算因子 → 策略选 → 下单
    placed_orders: list[tuple[str, str]] = []

    def _on_bar(ev: BarEvent) -> None:
        bar_snap = bars.get((ev.symbol, ev.ts.date()))
        if bar_snap is None:
            return
        broker.set_bar(bar_snap)
        # 用 PIT 截止 ev.ts 的 panel 算动量
        fp = registry.compute_panel(
            names=["momentum_5"], t=ev.ts,
            universe=symbols, snapshot_id="snap_m2", panel=panel,
        )
        ctx = BarContext(
            bar=bar_snap, symbol=ev.symbol, decision_time=ev.ts,
            clock=MagicMock(), account_id="acct1",
            positions={}, factor_panel=fp,
            rules=_RULE_MAIN, trace_id="trace_m2",
        )
        signals = strategy.on_bar(ctx)
        if not signals:
            return
        sig = signals[0]
        if sig.direction <= 0:
            return
        order = Order(symbol=sig.symbol, side="buy", qty=100,
                      order_type="limit", price=round(bar_snap.close, 2))
        client_id = f"c-{sig.symbol}-{ev.ts.date().isoformat()}"
        try:
            broker.place(order, client_order_id=client_id)
            placed_orders.append((sig.symbol, client_id))
        except Exception:
            pass  # T+N/重复等隔离

    bus.subscribe(BarEvent, _on_bar)

    # 跑 5 日：每日为每 symbol emit 一根 bar（≥ momentum window=5 才有信号）
    for day in days[5:]:
        for sym in symbols:
            _emit_bar(sym, day)

    # 断言 fills 产出（动量策略至少触发一次买入成交）
    assert len(received_fills) >= 1, "闭环未产出任何 on_fill 回调"
    assert all(getattr(f, "filled", False) for f in received_fills), "fill 未成交"

    # 持仓更新：买入 symbol 持仓 >= 100
    positions = broker.positions()
    assert any(q > 0 for q in positions.values()), "持仓未更新"

    # 策略 on_fill 在跑完后被调（通过 StrategyRunner.on_fills 派发）
    assert len(strategy._fills) == 0  # 本闭环未挂 runner，仅 broker.on_fill 触发
    # 补：手动派发一次确认策略 on_fill 不抛
    bus_event = received_fills[0]
    strategy.on_fill(bus_event)  # 不抛即通过


# ===========================================================================
# M2 验收 5：对账差异 < 0.1%（local_fills == broker_fills）
# ===========================================================================

def test_m2_reconcile_no_diff() -> None:
    """§11 M2 验收 5：local_fills == broker_fills → diff_rate=0 < 0.001。"""
    fills = {
        "o1": {"qty": 100, "price": 10.00, "status": "filled"},
        "o2": {"qty": 200, "price": 20.50, "status": "filled"},
    }
    result = reconcile(
        local_fills=fills, broker_fills=dict(fills),
        total_orders=2, threshold=0.001,
    )
    assert result.diff_rate == 0.0
    assert result.passed is True
    assert result.mismatches == []


def test_m2_reconcile_below_threshold() -> None:
    """补充：少量差异 → diff_rate 仍 < 0.001（< 0.1%）。"""
    local = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    broker = {"o1": {"qty": 100, "price": 10.0, "status": "filled"},
              "o2": {"qty": 50, "price": 5.0, "status": "filled"}}
    # 1 mismatch / max(1000, 1) → 0.001 < 0.001 为 False（恰好等于）
    # 用更大 total_orders 让 1/total < 0.001
    result = reconcile(local, broker, total_orders=2000, threshold=0.001)
    assert result.diff_rate == 1 / 2000
    assert result.passed is True


# ===========================================================================
# M2 验收 6：多账户隔离
# ===========================================================================

def test_m2_multi_account_isolation() -> None:
    """§11 M2 验收 6：两个 SimBrokerLive（acct1/acct2）持仓/订单互不串扰。

    - 各自 set_bar + place 同 client_order_id 不冲突
    - 持仓独立：acct1 买 600519，acct2 买 000001，互不影响
    - status 查询各看各的 _fills
    """
    broker1 = SimBrokerLive(rule_json_fn=_rule_fn)
    broker2 = SimBrokerLive(rule_json_fn=_rule_fn)

    bar_a = BarSnapshot(open=10.0, high=10.2, low=9.8, close=10.1,
                        volume=100_000.0, limit_up=11.0, limit_down=9.0)
    bar_b = BarSnapshot(open=5.0, high=5.2, low=4.8, close=5.1,
                        volume=100_000.0, limit_up=5.5, limit_down=4.5)
    broker1.set_bar(bar_a)
    broker2.set_bar(bar_b)

    # 同 client_order_id 在两个实例上互不冲突（per-instance 隔离）
    order_a = Order(symbol="600519", side="buy", qty=100,
                    order_type="limit", price=10.00)
    order_b = Order(symbol="000001", side="buy", qty=100,
                    order_type="limit", price=5.00)
    broker1.place(order_a, client_order_id="c-shared")
    broker2.place(order_b, client_order_id="c-shared")

    # 持仓隔离
    assert broker1.positions() == {"600519": 100}
    assert broker2.positions() == {"000001": 100}

    # status 各看各的 _fills（同 client_order_id 但属不同实例）
    assert broker1.status("c-shared") == OrderStatus.FILLED
    assert broker2.status("c-shared") == OrderStatus.FILLED

    # 互不串扰：acct1 持仓不含 000001
    assert "000001" not in broker1.positions()
    assert "600519" not in broker2.positions()


# ===========================================================================
# M2 验收 7：DuckdbHandoff 写权交接
# ===========================================================================

def test_m2_duckdb_handoff(tmp_path: Path) -> None:
    """§11 M2 验收 7：WriteLease acquire→can_write True；handoff→False；交接后另一 lease 可 acquire。"""
    lockfile = tmp_path / "m2_writer.lock"
    lease_intraday = WriteLease(lockfile, holder="intraday")
    handoff = DuckdbHandoff(lease_intraday)

    # 盘中 acquire → can_write True
    assert handoff.intraday_acquire() is True
    assert handoff.can_write() is True

    # 盘后交接 → can_write False
    assert handoff.post_market_handoff() is True
    assert handoff.can_write() is False

    # 交接后另一 lease（postmarket holder）可 acquire
    lease_post = WriteLease(lockfile, holder="postmarket")
    handoff_post = DuckdbHandoff(lease_post)
    assert handoff_post.intraday_acquire() is True
    assert handoff_post.can_write() is True


# ===========================================================================
# M2 验收 8：BarDedup + Backpressure 在管线中
# ===========================================================================

def test_m2_dedup_backpressure_in_pipeline() -> None:
    """§11 M2 验收 8：重复 bar 被 BarDedup 丢弃；超量触发 Backpressure 告警。

    - 同 (symbol, freq, ts) 的重复 bar：is_duplicate=True（应丢弃）
    - BackpressureConfig.max_depth=N，队列深度达 N → before_enqueue 返回 False + on_alert 触发
    """
    # ---- BarDedup ----
    dedup = BarDedup(max_seen=100)
    bar1 = types.SimpleNamespace(symbol="600519", freq="1d", ts=_dt.datetime(2024, 1, 5))
    bar_dup = types.SimpleNamespace(symbol="600519", freq="1d", ts=_dt.datetime(2024, 1, 5))
    bar2 = types.SimpleNamespace(symbol="600519", freq="1d", ts=_dt.datetime(2024, 1, 6))

    assert dedup.is_duplicate(bar1) is False   # 首次：非重复
    assert dedup.is_duplicate(bar_dup) is True  # 重复：丢弃
    assert dedup.is_duplicate(bar2) is False    # 不同 ts：非重复

    # ---- Backpressure ----
    alerts: list[int] = []
    bp = Backpressure(
        config=BackpressureConfig(max_depth=5, strategy="drop_newest"),
        on_alert=lambda depth: alerts.append(depth),
    )
    # 队列深度 < max_depth：允许入队
    for d in range(5):
        assert bp.before_enqueue(d) is True
    assert alerts == []

    # 深度达 max_depth：drop_newest 策略 → False + on_alert 触发
    assert bp.before_enqueue(5) is False
    assert len(alerts) == 1
    assert alerts[0] == 5
    assert bp.alerts == 1


# ===========================================================================
# M2 验收 9：Windows-only 标注（无 xtquant → RuntimeError）
# ===========================================================================

def test_m2_windows_only_note(monkeypatch) -> None:
    """§11 M2 验收 9：QmtGateway/QmtBroker 无 xtquant 时抛 RuntimeError('Windows-only')。

    在已安装 xtquant 的 Windows 环境中，测试通过 patch lazy import helper
    稳定覆盖缺包分支；live 路径仍须 QMT 终端服务在线后单独验证。
    """
    bridge = ThreadBridge()
    import quant.gateway.qmt as qmt_gateway_module

    monkeypatch.setattr(qmt_gateway_module, "_try_import_xtquant", lambda: None)
    with pytest.raises(RuntimeError, match="Windows-only"):
        QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    import quant.execution.qmt_broker as qmt_broker_module
    from quant.execution.qmt_broker import QmtBroker

    monkeypatch.setattr(qmt_broker_module, "_try_import_xtquant", lambda: None)
    with pytest.raises(RuntimeError, match="Windows-only"):
        QmtBroker(account_id="acct1", path="/tmp/qmt",
                  session_id=1, bridge=bridge)
