"""行情网关抽象（§4.1.1 + §3.1 数据流）。

行情网关向策略层提供统一的订阅与查询接口；具体实现（xtquant、回放等）
实现本 Protocol。history/bar_at 必须满足 PIT 安全——以 available_at 为
可见性判定，防止 look-ahead。
"""
from datetime import datetime
from typing import Callable, Protocol, runtime_checkable

import pandas as pd

# 复用 quant.events.BarEvent，避免重复定义
__all__ = ["MarketDataGateway", "BarEvent"]

# 显式 re-export，方便上层 from quant.gateway.base import BarEvent
from quant.events import BarEvent  # noqa: E402


@runtime_checkable
class MarketDataGateway(Protocol):
    """行情网关协议。

    所有时点查询（history / bar_at）必须基于 available_at 做 PIT 安全过滤，
    决策只能看到「在该决策时刻已经对外可见」的数据。
    """

    def subscribe(
        self, symbols: list[str], freq: str, on_bar: Callable[[BarEvent], None]
    ) -> None:
        """订阅实时 bar 推送。具体实现需把内部线程回调桥接到 asyncio loop。"""
        ...

    def history(
        self,
        symbol: str,
        freq: str,
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        """查询历史 bar。给定 as_of 时仅返回 available_at <= as_of 的行（防 look-ahead）。"""
        ...

    def bar_at(
        self,
        symbol: str,
        freq: str,
        t: datetime,
        decision_time: datetime,
    ) -> object | None:
        """返回 t 时刻的 bar；仅当 bar.available_at <= decision_time 时返回，否则 None。"""
        ...
