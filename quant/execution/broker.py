"""执行层抽象：订单状态机 + Broker Protocol（设计 v0.5 §4.6.1/§4.6.2）。

- 订单状态机：PENDING → SUBMITTED → PARTIAL_FILLED → FILLED，终态 CANCELLED/REJECTED。
  终态不可迁出，非法迁移抛 ValueError，保证幂等可恢复。
- Broker Protocol：执行适配器接口（place/cancel/status/positions/account/on_fill）。
  is_synchronous 区分同步撮合（回测）与异步回报（实盘网关）。
- DuplicateOrderError：client_order_id 重复（§4.6.2 断线重连防重复下单）。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Protocol


class OrderStatus(str, Enum):
    """订单生命周期状态（§4.6.1）。str Enum 便于序列化入库 order_event.payload。"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# 合法状态迁移图（§4.6.1）：
#   PENDING → SUBMITTED / REJECTED / CANCELLED
#   SUBMITTED → PARTIAL_FILLED / FILLED / CANCELLED / REJECTED
#   PARTIAL_FILLED → FILLED / CANCELLED
#   终态 FILLED / CANCELLED / REJECTED 不可迁出
_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {
        OrderStatus.SUBMITTED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    },
    OrderStatus.PARTIAL_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


def transition_allowed(from_s: OrderStatus, to_s: OrderStatus) -> bool:
    """查询迁移是否合法。"""
    return to_s in _TRANSITIONS.get(from_s, set())


def transition(from_s: OrderStatus, to_s: OrderStatus) -> OrderStatus:
    """执行迁移；非法抛 ValueError。"""
    if not transition_allowed(from_s, to_s):
        raise ValueError(f"非法状态迁移: {from_s.value} -> {to_s.value}")
    return to_s


class DuplicateOrderError(Exception):
    """client_order_id 重复（断线重连防重复下单，§4.6.2）。"""


class Broker(Protocol):
    """执行适配器协议（§4.6.2）。

    - 实盘实现（xtquant 等）：异步，回报经 on_fill 回调推送。
    - 回测实现：同步，place 内部即完成撮合。
    """

    is_synchronous: bool

    def place(self, order: Any, client_order_id: str) -> str:
        """下单，返回 broker order_id。client_order_id 用于幂等。"""
        ...

    def cancel(self, order_id: str) -> None:
        """撤单。"""
        ...

    def status(self, order_id: str) -> OrderStatus:
        """查询订单状态。"""
        ...

    def positions(self) -> list:
        """查询持仓快照。"""
        ...

    def account(self) -> dict:
        """查询账户资金。"""
        ...

    def on_fill(self, callback: Callable[[dict], None]) -> None:
        """注册成交回报回调（异步入口）。"""
        ...
