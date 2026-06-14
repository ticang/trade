"""M1.5 策略引擎契约测试：Signal / BarContext / FillContext。

仅校验数据结构装配与默认值，不涉及策略逻辑本身（§4.4.1）。
"""
from datetime import datetime

import pandas as pd

from quant.backtest.engine import Position
from quant.backtest.sim_broker import BarSnapshot
from quant.clock import BacktestClock
from quant.strategy.context import BarContext, FillContext
from quant.strategy.signal import Signal


def _make_bar() -> BarSnapshot:
    return BarSnapshot(
        open=10.0, high=10.5, low=9.8, close=10.2,
        volume=100000, limit_up=11.0, limit_down=9.0,
    )


def test_signal_defaults():
    # 仅 symbol/direction/strength 必填，其余走默认
    sig = Signal(symbol="600519", direction=1, strength=0.5)
    assert sig.symbol == "600519"
    assert sig.direction == 1
    assert sig.strength == 0.5
    assert sig.target_weight == 0.0
    assert sig.stop_loss is None
    assert sig.take_profit is None
    assert sig.trailing is None
    assert sig.reason == ""


def test_signal_fields():
    sig = Signal(
        symbol="000001",
        direction=-1,
        strength=0.8,
        target_weight=0.3,
        stop_loss=9.5,
        take_profit=11.5,
        trailing=0.05,
        reason="动量反转",
    )
    assert sig.direction == -1
    assert sig.strength == 0.8
    assert sig.target_weight == 0.3
    assert sig.stop_loss == 9.5
    assert sig.take_profit == 11.5
    assert sig.trailing == 0.05
    assert sig.reason == "动量反转"


def test_bar_context_assembly():
    clock = BacktestClock(datetime(2024, 1, 2, 15, 0))
    positions = {"600519": Position(qty=100, avg_cost=10.0)}
    panel = pd.DataFrame({"momentum": [0.1]}, index=["600519"])
    ctx = BarContext(
        bar=_make_bar(),
        symbol="600519",
        decision_time=datetime(2024, 1, 2, 15, 0),
        clock=clock,
        account_id="acct-1",
        positions=positions,
        factor_panel=panel,
        rules={"limit_up_pct": 0.1},
        trace_id="trace-001",
    )
    assert ctx.symbol == "600519"
    assert ctx.bar.close == 10.2
    assert ctx.clock.now() == datetime(2024, 1, 2, 15, 0)
    assert ctx.account_id == "acct-1"
    assert ctx.positions["600519"].qty == 100
    assert ctx.rules == {"limit_up_pct": 0.1}
    assert ctx.trace_id == "trace-001"
    assert ctx.decision_time == datetime(2024, 1, 2, 15, 0)


def test_fill_context_assembly():
    positions = {"600519": Position(qty=100, avg_cost=10.0)}
    fill = {"symbol": "600519", "side": "buy", "price": 10.1, "qty": 100, "cost": 1010.0}
    ctx = FillContext(
        fill=fill,
        account_id="acct-1",
        positions=positions,
        decision_time=datetime(2024, 1, 2, 15, 0),
        trace_id="trace-002",
    )
    assert ctx.fill["symbol"] == "600519"
    assert ctx.fill["qty"] == 100
    assert ctx.account_id == "acct-1"
    assert ctx.positions["600519"].avg_cost == 10.0
    assert ctx.trace_id == "trace-002"


def test_bar_context_factor_panel_is_dataframe():
    ctx = BarContext(
        bar=_make_bar(),
        symbol="600519",
        decision_time=datetime(2024, 1, 2, 15, 0),
        clock=BacktestClock(datetime(2024, 1, 2, 15, 0)),
        account_id="acct-1",
        positions={},
        factor_panel=pd.DataFrame({"f": [1.0]}),
        rules={},
    )
    assert isinstance(ctx.factor_panel, pd.DataFrame)
