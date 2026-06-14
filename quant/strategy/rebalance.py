"""再平衡策略与止损止盈触发（§4.4.4）。

提供：
- RebalancePolicy：定时（daily/weekly）/事件驱动/漂移超阈的再平衡判定。
- stop_loss_signals：持仓级止损、止盈、跟踪止损触发，产出卖 Signal。
"""
from dataclasses import dataclass
from datetime import date

from quant.strategy.signal import Signal


@dataclass
class RebalancePolicy:
    """再平衡策略：判定今日是否应再平衡。

    frequency 取值：
    - 'daily'  日频：today != last_rebalance 即触发。
    - 'weekly' 周频：距上次 >= 7 天即触发。
    - 'event'  事件驱动：仅由 event_triggered 决定。
    - 'drift'  漂移超阈：Σ|current-target|/2 > drift_threshold 触发。

    本类只判定是否触发，不改自身状态；触发后调用方应更新 last_rebalance=today。
    """

    frequency: str = "daily"
    drift_threshold: float = 0.05
    last_rebalance: date | None = None

    def should_rebalance(
        self,
        today: date,
        current_weights: dict | None = None,
        target_weights: dict | None = None,
        event_triggered: bool = False,
    ) -> bool:
        if self.frequency == "event":
            return event_triggered

        if self.frequency == "daily":
            # 从未再平衡（last_rebalance=None）或日期不同即触发
            return self.last_rebalance is None or today != self.last_rebalance

        if self.frequency == "weekly":
            if self.last_rebalance is None:
                return True
            return (today - self.last_rebalance).days >= 7

        if self.frequency == "drift":
            # 漂移量 = Σ|current-target| / 2（等价于需要调仓的单边权重总和）
            if not current_weights or not target_weights:
                return False
            symbols = set(current_weights) | set(target_weights)
            drift = sum(
                abs(current_weights.get(s, 0.0) - target_weights.get(s, 0.0))
                for s in symbols
            ) / 2.0
            return drift > self.drift_threshold

        return False


def stop_loss_signals(
    positions: dict,
    bars_today: dict,
    stop_loss_pct: float = 0.10,
    take_profit_pct: float = 0.20,
    trailing_pct: float | None = None,
    peak_since_entry: dict | None = None,
) -> list[Signal]:
    """持仓级止损止盈扫描：对超阈持仓产出卖 Signal（direction=-1）。

    每个持仓最多产 1 个信号，按优先级判定：止损 → 止盈 → 跟踪止损。
    positions: {symbol: Position(qty, avg_cost)}；
    bars_today: {symbol: BarSnapshot(last)}，last 取当日收盘价；
    peak_since_entry: {symbol: peak_price}（可选，trailing 用）。
    """
    peak_since_entry = peak_since_entry or {}
    signals: list[Signal] = []

    for symbol, pos in positions.items():
        avg_cost = getattr(pos, "avg_cost", None)
        bar = bars_today.get(symbol)
        if avg_cost is None or avg_cost <= 0 or bar is None:
            continue

        last = getattr(bar, "last", None)
        if last is None:
            # BarSnapshot 无 last 字段时回退取 close
            last = getattr(bar, "close", None)
        if last is None:
            continue

        ret = last / avg_cost - 1.0  # 浮动盈亏比例

        # 止损：浮亏超阈
        if ret <= -stop_loss_pct:
            signals.append(Signal(
                symbol=symbol, direction=-1, strength=1.0, reason="stop_loss",
            ))
            continue

        # 止盈：浮盈超阈
        if ret >= take_profit_pct:
            signals.append(Signal(
                symbol=symbol, direction=-1, strength=1.0, reason="take_profit",
            ))
            continue

        # 跟踪止损：从峰值回落超阈
        if trailing_pct is not None:
            peak = peak_since_entry.get(symbol)
            if peak and peak > 0 and (last / peak - 1.0) <= -trailing_pct:
                signals.append(Signal(
                    symbol=symbol, direction=-1, strength=1.0, reason="trailing",
                ))

    return signals
