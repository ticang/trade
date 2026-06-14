"""背压（§4.1.1）。

监控行情 bar 队列深度。超 max_depth 阈值时按策略降负（丢最新/丢最旧/合并），
并通过 on_alert 回调通知上层（告警/降频）。策略：
- drop_newest：丢当前条（False，不入队）
- drop_oldest：允许当前条（True），由调用方先丢最旧的再入队
- coalesce：合并中（False，调用方将本条并入队尾合并）
"""
from dataclasses import dataclass
from typing import Callable

__all__ = ["BackpressureConfig", "Backpressure"]


@dataclass
class BackpressureConfig:
    """背压配置。"""
    max_depth: int = 1000
    strategy: str = "drop_oldest"  # 'drop_oldest' | 'drop_newest' | 'coalesce'


class Backpressure:
    """队列深度监控；超阈值按策略降负 + 告警回调。"""

    def __init__(
        self,
        config: BackpressureConfig | None = None,
        on_alert: Callable[[int], None] | None = None,
    ) -> None:
        self.config = config or BackpressureConfig()
        self._on_alert = on_alert
        self._alerts = 0

    def before_enqueue(self, depth: int) -> bool:
        """入队前调：depth=当前队列深度。返回 True=允许入队，False=应丢弃。"""
        if depth < self.config.max_depth:
            return True
        strategy = self.config.strategy
        if strategy == "drop_oldest":
            allowed = True   # 调用方先丢最旧再入队
        elif strategy in ("drop_newest", "coalesce"):
            allowed = False  # 丢本条 / 合并中
        else:
            raise ValueError(f"unknown backpressure strategy: {strategy}")
        self._alerts += 1
        if self._on_alert is not None:
            self._on_alert(depth)
        return allowed

    @property
    def alerts(self) -> int:
        return self._alerts
