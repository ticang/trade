from datetime import datetime, timedelta
from typing import Protocol, Union


class Clock(Protocol):
    """时钟抽象：获取当前时刻。"""

    def now(self) -> datetime: ...


class LiveClock:
    """实盘时钟：返回真实当前时刻。"""

    def now(self) -> datetime:
        return datetime.now()


class BacktestClock:
    """回测时钟：确定性可控时刻。"""

    def __init__(self, start: datetime):
        self._t = start

    def now(self) -> datetime:
        return self._t

    def advance(self, dt: Union[timedelta, datetime]) -> None:
        # timedelta：按偏移前进；datetime：直接跳到该时刻
        self._t = dt if isinstance(dt, datetime) else self._t + dt
