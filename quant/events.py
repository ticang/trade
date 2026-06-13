import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, TypeVar

E = TypeVar("E")


@dataclass
class BarEvent:
    """K线事件。"""

    symbol: str
    freq: str
    ts: datetime
    close: float
    volume: float


class EventBus:
    """事件总线：按事件类型派发给订阅者，订阅者异常相互隔离。"""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, cb: Callable) -> None:
        self._subs.setdefault(event_type, []).append(cb)

    def publish(self, event: E) -> None:
        for cb in self._subs.get(type(event), []):
            try:
                cb(event)
            except Exception:
                # 订阅者异常不影响其他订阅者，仅记日志避免外抛
                logging.getLogger(__name__).exception("event subscriber raised")
