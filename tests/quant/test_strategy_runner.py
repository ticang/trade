"""StrategyRunner 测试：多策略并行调度 + 隔离 + 冲突裁决（§4.4.2）。

扁平测试：直接构造 BarContext，不依赖回测装配链路。
"""
from datetime import datetime

import pandas as pd

from quant.backtest.engine import Position
from quant.backtest.sim_broker import BarSnapshot
from quant.clock import BacktestClock
from quant.strategy.context import BarContext
from quant.strategy.runner import Strategy, StrategyRunner
from quant.strategy.signal import Signal


def _make_ctx() -> BarContext:
    """构造最小可用 BarContext（空因子面板、空持仓）。"""
    bar = BarSnapshot(
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=10000.0, limit_up=110.0, limit_down=90.0,
    )
    return BarContext(
        bar=bar,
        symbol="600519",
        decision_time=datetime(2024, 1, 2, 9, 35),
        clock=BacktestClock(datetime(2024, 1, 2, 9, 35)),
        account_id="acct1",
        positions={},
        factor_panel=pd.DataFrame(),
        rules={},
        trace_id="trace-test",
    )


class _BuyAll:
    """假策略：买 600519 与 000001。"""

    name = "buyall"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        return [Signal("600519", 1, 0.5, 0.3), Signal("000001", 1, 0.4, 0.2)]

    def on_fill(self, ctx) -> None:
        pass


class _Sell600519:
    """假策略：卖 600519，strength 0.8 主导，与 buyall 冲突。"""

    name = "sell"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        return [Signal("600519", -1, -0.8, 0.0)]

    def on_fill(self, ctx) -> None:
        pass


class _Crash:
    """假策略：on_bar 抛异常，验证隔离。"""

    name = "crash"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        raise RuntimeError("boom")

    def on_fill(self, ctx) -> None:
        pass


def _by_symbol(signals: list[Signal]) -> dict[str, Signal]:
    return {s.symbol: s for s in signals}


# 1. 单策略：register 后 run 返回其全部 Signal
def test_register_and_run_single() -> None:
    runner = StrategyRunner()
    runner.register(_BuyAll())
    ctx = _make_ctx()

    signals = runner.run(ctx)

    assert len(signals) == 2
    syms = {s.symbol for s in signals}
    assert syms == {"600519", "000001"}


# 2. 多策略冲突：600519 按 strength 加权合并，direction=sign(Σstrength)
def test_multi_strategy_merge() -> None:
    runner = StrategyRunner()
    runner.register(_BuyAll())
    runner.register(_Sell600519())
    ctx = _make_ctx()

    signals = runner.run(ctx)
    by = _by_symbol(signals)

    # 600519: Σstrength = 0.5 + (-0.8) = -0.3 → direction=-1
    assert "600519" in by
    merged = by["600519"]
    assert merged.direction == -1
    assert abs(merged.strength - (-0.3)) < 1e-9
    # target_weight 同样求和：0.3 + 0.0 = 0.3
    assert abs(merged.target_weight - 0.3) < 1e-9
    # 000001 无冲突，保持原样
    assert "000001" in by
    assert by["000001"].direction == 1


# 3. 隔离：单策略异常不阻断整 bar，仍返回其他策略 Signal
def test_isolation_crash_not_block() -> None:
    runner = StrategyRunner()
    runner.register(_BuyAll())
    runner.register(_Crash())
    ctx = _make_ctx()

    signals = runner.run(ctx)  # 不抛

    assert len(signals) == 2
    assert {s.symbol for s in signals} == {"600519", "000001"}


# 4. 冲突裁决：合并 strength 为各分量的和，direction 为其符号
def test_conflict_resolution_by_strength() -> None:
    runner = StrategyRunner()
    runner.register(_BuyAll())
    runner.register(_Sell600519())
    ctx = _make_ctx()

    by = _by_symbol(runner.run(ctx))
    merged = by["600519"]
    assert merged.strength == 0.5 + (-0.8)
    assert merged.direction == -1  # sign(-0.3)


# 5. 去重：每个 symbol 至多一条 Signal
def test_dedup_one_signal_per_symbol() -> None:
    runner = StrategyRunner()
    runner.register(_BuyAll())
    runner.register(_Sell600519())
    ctx = _make_ctx()

    signals = runner.run(ctx)
    syms = [s.symbol for s in signals]
    assert len(syms) == len(set(syms))


# 6. 无策略：run 返回空列表
def test_empty_strategies_returns_empty() -> None:
    runner = StrategyRunner()
    assert runner.run(_make_ctx()) == []
