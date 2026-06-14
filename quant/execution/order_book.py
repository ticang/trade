"""本地订单簿：由 order_event 重放恢复（设计 v0.5 §4.6.2）。

- client_order_id 去重：register 时校验，防止断线重连重复下单。
- apply_event：按事件类型推进订单状态（经 transition 校验），累积 filled_qty。
- replay：从 order_event 表按 ts 重放全部事件，幂等重建当前订单簿。
"""
from __future__ import annotations

import json
from typing import Any

from quant.data.sqlite_store import SqliteStore
from quant.execution.broker import (
    DuplicateOrderError,
    OrderStatus,
    transition,
)


# event_type → OrderStatus 映射（order_event.event_type 取值）
_EVENT_STATUS: dict[str, OrderStatus] = {
    "pending": OrderStatus.PENDING,
    "submitted": OrderStatus.SUBMITTED,
    "partial_filled": OrderStatus.PARTIAL_FILLED,
    "filled": OrderStatus.FILLED,
    "cancelled": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
}


class OrderBook:
    """本地订单簿：order_id → 订单视图（status / client_order_id / filled_qty）。

    由 order_event 重放恢复，支持 client_order_id 去重。
    """

    def __init__(self, store: SqliteStore | None = None):
        # store 仅作可选保留，重放由显式 replay(store) 触发
        self._store = store
        self._orders: dict[str, dict[str, Any]] = {}
        self._client_ids: set[str] = set()

    def register(self, order_id: str, client_order_id: str) -> None:
        """登记新订单：client_order_id 重复 → DuplicateOrderError。

        新订单初始状态为 PENDING；apply_event 后再推进。
        """
        if client_order_id in self._client_ids:
            raise DuplicateOrderError(
                f"client_order_id 已存在: {client_order_id}"
            )
        self._client_ids.add(client_order_id)
        self._orders[order_id] = {
            "status": OrderStatus.PENDING,
            "client_order_id": client_order_id,
            "filled_qty": 0,
        }

    def apply_event(
        self,
        order_id: str,
        event_type: str,
        payload: dict,
        ts: int,
    ) -> None:
        """应用一条 order_event：推进状态（transition 校验），累积 filled_qty。

        非法 event_type 或状态迁移抛 ValueError。未登记的 order_id 自动注册
        （replay 场景：order_event 可能先于 register 到达）。
        """
        target = _EVENT_STATUS.get(event_type)
        if target is None:
            raise ValueError(f"未知 event_type: {event_type}")

        if order_id not in self._orders:
            # 重放路径：order_event 中未带 client_order_id 信息，用 order_id 占位
            self._orders[order_id] = {
                "status": OrderStatus.PENDING,
                "client_order_id": order_id,
                "filled_qty": 0,
            }
            self._client_ids.add(order_id)

        cur = self._orders[order_id]
        cur["status"] = transition(cur["status"], target)

        # 成交类事件累积 filled_qty（partial_filled / filled 均携带本次成交量）
        filled = payload.get("filled_qty")
        if filled:
            cur["filled_qty"] += filled

    def status_of(self, order_id: str) -> OrderStatus | None:
        """查询订单当前状态；不存在返回 None。"""
        entry = self._orders.get(order_id)
        return entry["status"] if entry else None

    def replay(self, store: SqliteStore) -> None:
        """从 order_event 表按 ts 重放恢复全部订单状态。"""
        store.flush()
        rows = store.query_all(
            "SELECT order_id, event_type, payload, ts "
            "FROM order_event ORDER BY ts ASC"
        )
        for row in rows:
            payload = json.loads(row["payload"]) if row["payload"] else {}
            self.apply_event(
                row["order_id"], row["event_type"], payload, row["ts"]
            )
