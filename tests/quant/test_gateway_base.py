"""行情网关抽象 + 线程桥接测试（§4.1.1 + §3.1 数据流）。

覆盖：
- MarketDataGateway 协议结构（subscribe/history/bar_at）
- PIT 安全：bar_at 与 history 的 as_of 过滤防 look-ahead
- ThreadBridge：xtquant 内部线程回调 → asyncio loop 桥接
"""
import asyncio
import inspect
import threading
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from quant.events import BarEvent
from quant.gateway.base import MarketDataGateway
from quant.gateway.thread_bridge import ThreadBridge


# ---------------- Protocol 结构 ----------------

def test_protocol_structure():
    # MarketDataGateway 协议声明 subscribe/history/bar_at
    assert hasattr(MarketDataGateway, "subscribe")
    assert hasattr(MarketDataGateway, "history")
    assert hasattr(MarketDataGateway, "bar_at")
    # 方法签名存在必要参数
    sig_sub = inspect.signature(MarketDataGateway.subscribe)
    assert "symbols" in sig_sub.parameters
    assert "freq" in sig_sub.parameters
    assert "on_bar" in sig_sub.parameters
    sig_hist = inspect.signature(MarketDataGateway.history)
    assert "symbol" in sig_hist.parameters
    assert "freq" in sig_hist.parameters
    assert "as_of" in sig_hist.parameters
    sig_bar_at = inspect.signature(MarketDataGateway.bar_at)
    assert "decision_time" in sig_bar_at.parameters


# ---------------- PIT 安全：bar_at ----------------

def test_bar_at_pit_safe():
    # bar.available_at <= decision_time 返回 bar；> decision_time 返回 None（防 look-ahead）
    gw = _FakeGateway()
    bar_ready = _Bar(ts=datetime(2024, 3, 15, 15), close=10.0, available_at=datetime(2024, 3, 15, 15))
    bar_future = _Bar(ts=datetime(2024, 3, 15, 15), close=11.0, available_at=datetime(2024, 3, 15, 15, 30))
    gw.bars = {("600519", "1d", datetime(2024, 3, 15, 15)): [bar_ready],
               ("600519", "1d", datetime(2024, 3, 15, 15, 30)): [bar_future]}

    # decision_time 已晚于 available_at → 可见
    got = gw.bar_at("600519", "1d", datetime(2024, 3, 15, 15), datetime(2024, 3, 15, 15, 5))
    assert got is bar_ready
    # decision_time 早于 available_at → None（防 look-ahead）
    hidden = gw.bar_at("600519", "1d", datetime(2024, 3, 15, 15, 30), datetime(2024, 3, 15, 15, 10))
    assert hidden is None
    # 未知键 → None
    assert gw.bar_at("000001", "1d", datetime(2024, 1, 1), datetime(2024, 12, 31)) is None


def test_history_respects_as_of():
    # FakeGateway.history 仅返回 available_at <= as_of 的 bar
    gw = _FakeGateway()
    gw.history_rows = [
        {"ts": datetime(2024, 3, 14, 15), "close": 9.0, "available_at": datetime(2024, 3, 14, 15)},
        {"ts": datetime(2024, 3, 15, 15), "close": 10.0, "available_at": datetime(2024, 3, 15, 15)},
        {"ts": datetime(2024, 3, 15, 15, 30), "close": 11.0, "available_at": datetime(2024, 3, 15, 15, 30)},
    ]
    df = gw.history("600519", "1d", datetime(2024, 3, 14), datetime(2024, 3, 16), as_of=datetime(2024, 3, 15, 15))
    # 仅 available_at <= as_of 的两行可见，未来一行被过滤
    assert len(df) == 2
    assert all(av <= datetime(2024, 3, 15, 15) for av in df["available_at"])


# ---------------- ThreadBridge ----------------

def test_thread_bridge_calls_soon_threadsafe():
    # 绑定 mock loop + on_bar；bridge(bar) → loop.call_soon_threadsafe(on_bar, bar) 调用一次，参数正确
    loop = MagicMock()
    on_bar = MagicMock()
    bridge = ThreadBridge(loop=loop, on_bar=on_bar)
    bar = BarEvent(symbol="600519", freq="1d", ts=datetime(2024, 3, 15, 15), close=10.0, volume=100)
    bridge.bridge(bar)
    loop.call_soon_threadsafe.assert_called_once_with(on_bar, bar)


def test_thread_bridge_unbound_safe():
    # 未 bind loop 时 bridge(bar) 不崩（静默）
    bridge = ThreadBridge()
    bar = BarEvent(symbol="600519", freq="1d", ts=datetime(2024, 3, 15, 15), close=10.0, volume=100)
    # 不应抛异常
    bridge.bridge(bar)
    # 重新 bind 后仍可工作
    loop = MagicMock()
    on_bar = MagicMock()
    bridge.bind(loop, on_bar)
    bridge.bridge(bar)
    loop.call_soon_threadsafe.assert_called_once_with(on_bar, bar)


def test_thread_bridge_from_internal_thread():
    # 真线程场景：内部线程调 bridge，主线程 mock loop 收到 call_soon_threadsafe
    loop = MagicMock()
    on_bar = MagicMock()
    bridge = ThreadBridge(loop=loop, on_bar=on_bar)
    bar = BarEvent(symbol="600519", freq="1d", ts=datetime(2024, 3, 15, 15), close=10.0, volume=100)

    err: list[Exception] = []

    def worker() -> None:
        try:
            bridge.bridge(bar)
        except Exception as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert err == []
    loop.call_soon_threadsafe.assert_called_once_with(on_bar, bar)


# ---------------- 最小 FakeGateway ----------------

class _Bar:
    """内存 bar，带 available_at 用于 PIT 判定。"""
    __slots__ = ("ts", "close", "available_at")

    def __init__(self, ts: datetime, close: float, available_at: datetime) -> None:
        self.ts = ts
        self.close = close
        self.available_at = available_at


class _FakeGateway:
    """最小内存实现，满足 MarketDataGateway 协议，演示 PIT 安全语义。"""
    bars: dict
    history_rows: list[dict]
    _on_bars: dict

    def __init__(self) -> None:
        self.bars = {}
        self.history_rows = []
        self._on_bars = {}

    def subscribe(self, symbols, freq, on_bar) -> None:  # type: ignore[no-untyped-def]
        for s in symbols:
            self._on_bars[(s, freq)] = on_bar

    def history(self, symbol, freq, start, end, as_of=None) -> pd.DataFrame:  # type: ignore[no-untyped-def]
        rows = self.history_rows
        if as_of is not None:
            rows = [r for r in rows if r["available_at"] <= as_of]
        return pd.DataFrame(rows)

    def bar_at(self, symbol, freq, t, decision_time) -> object | None:  # type: ignore[no-untyped-def]
        candidates = self.bars.get((symbol, freq, t), [])
        for b in candidates:
            if b.available_at <= decision_time:
                return b
        return None
