"""bar 去重（§4.1.1）。

bar 唯一键 (symbol, freq, trade_ts)。断线重连重发的重复 bar 在网关层丢弃，
避免触发重复信号。采用 FIFO 循环缓冲：键集合超 max_seen 时按最早入序驱逐，
保证内存有界且去重器持续有效。
"""
from collections import deque
from typing import Any

__all__ = ["BarDedup"]


class BarDedup:
    """bar 去重：唯一键 (symbol, freq, trade_ts)，重复 bar 丢弃。"""

    def __init__(self, max_seen: int = 10000) -> None:
        if max_seen <= 0:
            raise ValueError("max_seen must be positive")
        self._seen: set[tuple] = set()
        self._order: deque[tuple] = deque()
        self._max = max_seen

    def key(self, bar: Any) -> tuple:
        # 兼容 ts / trade_ts 两种属性命名
        ts = getattr(bar, "ts", None)
        if ts is None:
            ts = getattr(bar, "trade_ts", None)
        return (getattr(bar, "symbol"), getattr(bar, "freq"), ts)

    def is_duplicate(self, bar: Any) -> bool:
        """True=重复（应丢弃）。新键加入 _seen；超 max_seen 时按 FIFO 驱逐旧键。"""
        k = self.key(bar)
        if k in self._seen:
            return True
        self._seen.add(k)
        self._order.append(k)
        if len(self._order) > self._max:
            oldest = self._order.popleft()
            self._seen.discard(oldest)
        return False

    def allow(self, bar: Any) -> bool:
        """is_duplicate 取反：True=允许通过。"""
        return not self.is_duplicate(bar)
