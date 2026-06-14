"""策略信号：策略产出的交易意图（§4.4.1）。
"""
from dataclasses import dataclass


@dataclass
class Signal:
    """单个标的的交易信号，作为组合优化器的输入。

    direction 约定：+1 多 / -1 空 / 0 平。
    """

    symbol: str
    direction: int              # +1 多 / -1 空 / 0 平
    strength: float             # 信号强度（alpha）
    target_weight: float = 0.0  # 目标权重（0~1），组合优化器输入
    stop_loss: float | None = None
    take_profit: float | None = None
    trailing: float | None = None  # 跟踪止损比例
    reason: str = ""
