"""再平衡策略与止损止盈触发测试（§4.4.4）。

覆盖：
- RebalancePolicy 四种再平衡模式（daily/weekly/event/drift）
- stop_loss_signals 持仓级止损/止盈/跟踪止损触发
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from quant.strategy.rebalance import RebalancePolicy, stop_loss_signals
from quant.strategy.signal import Signal


# 简化构造：Position(qty, avg_cost)、BarSnapshot(last=close)
def make_position(qty: int, avg_cost: float) -> SimpleNamespace:
    return SimpleNamespace(qty=qty, avg_cost=avg_cost)


def make_bar(last: float) -> SimpleNamespace:
    return SimpleNamespace(last=last)


# ---------- RebalancePolicy ----------

class TestRebalancePolicy:
    def test_daily_rebalance(self):
        # daily：today != last_rebalance 即触发；== last 不触发
        policy = RebalancePolicy(frequency="daily", last_rebalance=date(2026, 6, 10))
        assert policy.should_rebalance(date(2026, 6, 11)) is True
        assert policy.should_rebalance(date(2026, 6, 10)) is False

    def test_weekly_rebalance(self):
        # weekly：today - last < 7 天不触发；>= 7 天触发
        policy = RebalancePolicy(frequency="weekly", last_rebalance=date(2026, 6, 1))
        assert policy.should_rebalance(date(2026, 6, 4)) is False   # 3 天
        assert policy.should_rebalance(date(2026, 6, 8)) is True    # 7 天

    def test_event_rebalance(self):
        # event：仅由 event_triggered 决定
        policy = RebalancePolicy(frequency="event")
        assert policy.should_rebalance(date(2026, 6, 10), event_triggered=False) is False
        assert policy.should_rebalance(date(2026, 6, 10), event_triggered=True) is True

    def test_drift_rebalance(self):
        # drift：Σ|current-target|/2 超 threshold 触发
        policy = RebalancePolicy(frequency="drift", drift_threshold=0.05)
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.3, "B": 0.7}
        # drift = (|0.5-0.3| + |0.5-0.7|) / 2 = 0.2 > 0.05 → 触发
        assert policy.should_rebalance(
            date(2026, 6, 10), current_weights=current, target_weights=target
        ) is True
        # current == target → drift=0 不触发
        assert policy.should_rebalance(
            date(2026, 6, 10), current_weights=target, target_weights=target
        ) is False


# ---------- stop_loss_signals ----------

class TestStopLossSignals:
    def test_stop_loss_signal(self):
        # avg_cost=100，last=85 → -15% < -10% → 卖 Signal 'stop_loss'
        positions = {"600000": make_position(qty=100, avg_cost=100.0)}
        bars = {"600000": make_bar(last=85.0)}
        signals = stop_loss_signals(positions, bars, stop_loss_pct=0.10, take_profit_pct=0.20)
        assert len(signals) == 1
        s = signals[0]
        assert s.symbol == "600000"
        assert s.direction == -1
        assert s.reason == "stop_loss"
        assert s.strength == 1.0

    def test_take_profit_signal(self):
        # avg_cost=100，last=125 → +25% > +20% → 'take_profit'
        positions = {"600000": make_position(qty=100, avg_cost=100.0)}
        bars = {"600000": make_bar(last=125.0)}
        signals = stop_loss_signals(positions, bars, stop_loss_pct=0.10, take_profit_pct=0.20)
        assert len(signals) == 1
        assert signals[0].reason == "take_profit"
        assert signals[0].direction == -1

    def test_no_signal_when_within_range(self):
        # avg_cost=100，last=105 → +5%，范围内无信号
        positions = {"600000": make_position(qty=100, avg_cost=100.0)}
        bars = {"600000": make_bar(last=105.0)}
        signals = stop_loss_signals(positions, bars, stop_loss_pct=0.10, take_profit_pct=0.20)
        assert signals == []

    def test_trailing_stop_signal(self):
        # peak=130，last=117 → 117/130-1 ≈ -10%，trailing_pct=0.08 → 'trailing'
        positions = {"600000": make_position(qty=100, avg_cost=100.0)}
        bars = {"600000": make_bar(last=117.0)}
        peak = {"600000": 130.0}
        signals = stop_loss_signals(
            positions, bars,
            stop_loss_pct=0.10, take_profit_pct=0.20,
            trailing_pct=0.08, peak_since_entry=peak,
        )
        reasons = [s.reason for s in signals]
        assert "trailing" in reasons

    def test_multiple_positions(self):
        # 3 持仓，仅 1 触止损 → 返回 1 Signal
        positions = {
            "600000": make_position(qty=100, avg_cost=100.0),   # last=85 触止损
            "600001": make_position(qty=100, avg_cost=100.0),   # last=100 范围内
            "600002": make_position(qty=100, avg_cost=100.0),   # last=102 范围内
        }
        bars = {
            "600000": make_bar(last=85.0),
            "600001": make_bar(last=100.0),
            "600002": make_bar(last=102.0),
        }
        signals = stop_loss_signals(positions, bars, stop_loss_pct=0.10, take_profit_pct=0.20)
        assert len(signals) == 1
        assert signals[0].symbol == "600000"
        assert signals[0].reason == "stop_loss"
