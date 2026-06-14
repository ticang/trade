"""bar 去重 + 背压测试（§4.1.1）。

覆盖：
- BarDedup：唯一键 (symbol,freq,trade_ts)，重复 bar 丢弃，max_seen 驱逐
- Backpressure：队列深度监控；超阈值按策略降负 + 告警回调
"""
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

from quant.gateway.backpressure import Backpressure, BackpressureConfig
from quant.gateway.dedup import BarDedup


# ---------------- 测试用 bar ----------------

@dataclass
class _Bar:
    """内存 bar，复用 BarEvent 语义（symbol/freq/ts）。"""
    symbol: str
    freq: str
    ts: datetime
    close: float = 10.0


def _bar(symbol: str = "600519", freq: str = "1d", ts: datetime | None = None) -> _Bar:
    return _Bar(symbol=symbol, freq=freq, ts=ts or datetime(2024, 3, 15, 15))


# ---------------- BarDedup ----------------

def test_dedup_new_bar_allowed():
    # 新 bar allow()=True
    dd = BarDedup()
    assert dd.allow(_bar()) is True


def test_dedup_duplicate_dropped():
    # 同 (symbol,freq,ts) 第二次 is_duplicate=True
    dd = BarDedup()
    b = _bar()
    assert dd.is_duplicate(b) is False  # 第一次：不重复
    assert dd.is_duplicate(b) is True   # 第二次：重复


def test_dedup_different_keys_allowed():
    # 不同 symbol/ts 都 allow
    dd = BarDedup()
    b1 = _bar(symbol="600519", ts=datetime(2024, 3, 15, 15))
    b2 = _bar(symbol="000001", ts=datetime(2024, 3, 15, 15))
    b3 = _bar(symbol="600519", ts=datetime(2024, 3, 14, 15))
    assert dd.allow(b1) is True
    assert dd.allow(b2) is True
    assert dd.allow(b3) is True


def test_dedup_max_seen_eviction():
    # 超 max_seen 不崩：旧键被清，去重器仍工作
    dd = BarDedup(max_seen=3)
    # 填满 3 个不同键
    for i in range(3):
        assert dd.allow(_bar(ts=datetime(2024, 3, 1 + i, 15))) is True
    # 第 4 个键触发驱逐；不应抛异常
    assert dd.allow(_bar(ts=datetime(2024, 3, 10, 15))) is True
    # 去重器仍可用：新键 allow，刚加的键判重
    assert dd.is_duplicate(_bar(ts=datetime(2024, 3, 10, 15))) is True


# ---------------- Backpressure ----------------

def test_backpressure_under_threshold():
    # depth<max → before_enqueue=True
    bp = Backpressure(BackpressureConfig(max_depth=1000, strategy="drop_newest"))
    assert bp.before_enqueue(depth=0) is True
    assert bp.before_enqueue(depth=999) is True
    assert bp.alerts == 0


def test_backpressure_drop_newest():
    # depth>=max, strategy=drop_newest → False + on_alert 触发
    alerted = MagicMock()
    bp = Backpressure(BackpressureConfig(max_depth=1000, strategy="drop_newest"), on_alert=alerted)
    assert bp.before_enqueue(depth=1000) is False
    alerted.assert_called_once_with(1000)
    assert bp.alerts == 1


def test_backpressure_drop_oldest():
    # strategy=drop_oldest → True + alert（调用方丢旧）
    alerted = MagicMock()
    bp = Backpressure(BackpressureConfig(max_depth=500, strategy="drop_oldest"), on_alert=alerted)
    assert bp.before_enqueue(depth=500) is True
    alerted.assert_called_once_with(500)
    assert bp.alerts == 1


def test_backpressure_alert_count():
    # 多次超阈值 → alerts 累计
    alerted = MagicMock()
    bp = Backpressure(BackpressureConfig(max_depth=100, strategy="drop_newest"), on_alert=alerted)
    for _ in range(3):
        bp.before_enqueue(depth=100)
    assert bp.alerts == 3
    assert alerted.call_count == 3
