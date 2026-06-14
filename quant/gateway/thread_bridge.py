"""线程桥接（§4.1.1 + §3.1 数据流）。

xtquant 的实时回调发生在内部线程，而策略消费在 asyncio loop 上。
ThreadBridge 持有目标 loop 与 on_bar 回调，内部线程通过 bridge(bar)
跨线程把 bar 投递到 loop（call_soon_threadsafe），保证事件总线只在
loop 线程上 publish，避免并发竞态。
"""
import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["ThreadBridge"]


class ThreadBridge:
    """xtquant 内部线程 → asyncio loop 桥接器。

    用法：
        bridge = ThreadBridge()
        bridge.bind(loop, on_bar)
        # xtquant 回调中（内部线程）调用：
        bridge.bridge(bar)   # → loop.call_soon_threadsafe(on_bar, bar)
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        on_bar: Callable[[Any], None] | None = None,
    ) -> None:
        self._loop = loop
        self._on_bar = on_bar

    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        on_bar: Callable[[Any], None],
    ) -> None:
        # 绑定（或重绑）目标 loop 与回调
        self._loop = loop
        self._on_bar = on_bar

    def bridge(self, bar: Any) -> None:
        """内部线程入口：安全地把 bar 投递到 loop。

        loop 未绑定或未运行时静默丢弃并记日志，防止内部线程崩溃拖垮行情线程。
        """
        loop = self._loop
        on_bar = self._on_bar
        if loop is None or on_bar is None:
            logger.debug("ThreadBridge unbound, drop bar: %r", bar)
            return
        if not loop.is_running():
            logger.warning("ThreadBridge target loop not running, drop bar: %r", bar)
            return
        loop.call_soon_threadsafe(on_bar, bar)
