"""StrategyRunner：多策略并行调度 + 隔离 + 冲突裁决（§4.4.2）。

职责：
- 并行调度各策略 on_bar，每策略异常隔离（记日志不阻断整 bar）。
- 同 symbol 多 Signal 冲突裁决：strength 加权合并为单 Signal。
"""
import logging
from typing import Protocol

from quant.strategy.context import BarContext, FillContext
from quant.strategy.signal import Signal

logger = logging.getLogger(__name__)


class Strategy(Protocol):
    """策略协议：Runner 调度的最小单元。"""

    name: str
    required_factors: list[str]

    def on_bar(self, ctx: BarContext) -> list[Signal]: ...
    def on_fill(self, ctx: FillContext) -> None: ...


def _merge(signals: list[Signal]) -> Signal:
    """同 symbol 多 Signal 加权合并：strength/target_weight 求和，direction 取符号。

    stop_loss/take_profit/trailing/reason 取首个非默认值，保持可追溯。
    """
    symbol = signals[0].symbol
    strength = sum(s.strength for s in signals)
    target_weight = sum(s.target_weight for s in signals)
    direction = 0 if strength == 0 else (1 if strength > 0 else -1)

    stop_loss = next((s.stop_loss for s in signals if s.stop_loss is not None), None)
    take_profit = next((s.take_profit for s in signals if s.take_profit is not None), None)
    trailing = next((s.trailing for s in signals if s.trailing is not None), None)
    reason = " | ".join(s.reason for s in signals if s.reason)

    return Signal(
        symbol=symbol,
        direction=direction,
        strength=strength,
        target_weight=target_weight,
        stop_loss=stop_loss,
        take_profit=take_profit,
        trailing=trailing,
        reason=reason,
    )


class StrategyRunner:
    """多策略调度器：注册 → run 装配冲突裁决后的 Signal 列表。"""

    def __init__(self) -> None:
        self._strategies: list[Strategy] = []

    def register(self, strategy: Strategy) -> None:
        self._strategies.append(strategy)

    def run(self, ctx: BarContext) -> list[Signal]:
        """并行调各策略 on_bar（异常隔离），收集并按 symbol 冲突裁决。

        返回去重后的 Signal 列表，每个 symbol 至多一条。
        """
        # 按 symbol 聚合所有策略产出的 Signal
        bucket: dict[str, list[Signal]] = {}
        for strategy in self._strategies:
            try:
                produced = strategy.on_bar(ctx)
            except Exception:
                # 单策略异常隔离：记日志不阻断本 bar 其他策略
                logger.exception("strategy %s on_bar failed", getattr(strategy, "name", strategy))
                continue
            for sig in produced or []:
                bucket.setdefault(sig.symbol, []).append(sig)

        # 每 symbol 多 Signal 合并为单条；单 Signal 原样保留
        resolved: list[Signal] = []
        for signals in bucket.values():
            resolved.append(signals[0] if len(signals) == 1 else _merge(signals))
        return resolved

    def on_fills(self, ctx_factory, fills: list) -> None:
        """对每个 fill 构造 FillContext 调各策略 on_fill（异常隔离）。

        ctx_factory(fill) -> FillContext，由调用方装配上下文。
        """
        for fill in fills:
            ctx = ctx_factory(fill)
            for strategy in self._strategies:
                try:
                    strategy.on_fill(ctx)
                except Exception:
                    logger.exception(
                        "strategy %s on_fill failed", getattr(strategy, "name", strategy)
                    )
