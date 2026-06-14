"""执行层抽象：Broker Protocol + 订单状态机 + 本地订单簿测试。

覆盖设计 v0.5 §4.6.1（订单状态机）+ §4.6.2（Broker Protocol 与 client_order_id 去重、
order_event 重放恢复）。

TDD：本文件先于 broker.py / order_book.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.execution.broker import (
    Broker,
    DuplicateOrderError,
    OrderStatus,
    transition,
    transition_allowed,
)
from quant.execution.order_book import OrderBook


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite(tmp_path):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    s = SqliteStore(str(tmp_path / "exec.db"))
    s.start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# 订单状态机：合法迁移图（§4.6.1）
# ---------------------------------------------------------------------------


def test_status_transitions_legal():
    """合法迁移：PENDING→SUBMITTED→FILLED。中间态与终态可达。"""
    assert transition_allowed(OrderStatus.PENDING, OrderStatus.SUBMITTED)
    assert transition_allowed(OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED)
    assert transition_allowed(OrderStatus.PARTIAL_FILLED, OrderStatus.FILLED)
    assert transition(OrderStatus.PENDING, OrderStatus.SUBMITTED) == OrderStatus.SUBMITTED
    assert transition(OrderStatus.SUBMITTED, OrderStatus.FILLED) == OrderStatus.FILLED


def test_status_transitions_illegal():
    """非法迁移：跳级（PENDING→FILLED）抛 ValueError；终态（FILLED）不可迁出。"""
    assert not transition_allowed(OrderStatus.PENDING, OrderStatus.FILLED)
    assert not transition_allowed(OrderStatus.FILLED, OrderStatus.CANCELLED)
    assert not transition_allowed(OrderStatus.REJECTED, OrderStatus.SUBMITTED)

    with pytest.raises(ValueError):
        transition(OrderStatus.PENDING, OrderStatus.FILLED)
    with pytest.raises(ValueError):
        transition(OrderStatus.FILLED, OrderStatus.CANCELLED)


# ---------------------------------------------------------------------------
# client_order_id 去重（§4.6.2 断线重连防重复下单）
# ---------------------------------------------------------------------------


def test_client_order_id_dedup():
    """同 client_order_id 二次注册 → DuplicateOrderError。"""
    book = OrderBook()
    book.register("order-1", "client-1")
    with pytest.raises(DuplicateOrderError):
        book.register("order-2", "client-1")


# ---------------------------------------------------------------------------
# OrderBook.apply_event：事件驱动状态推进 + filled_qty 累积
# ---------------------------------------------------------------------------


def test_order_book_apply_event():
    """SUBMITTED → PARTIAL_FILLED（累积 100）→ FILLED（累积 200）。
    apply_event 更新 status 与 filled_qty。"""
    book = OrderBook()
    book.register("o-1", "c-1")

    book.apply_event("o-1", "submitted", {"broker_order_id": "b-1"}, ts=1)
    assert book.status_of("o-1") == OrderStatus.SUBMITTED

    book.apply_event(
        "o-1", "partial_filled", {"filled_qty": 100, "price": 10.0}, ts=2
    )
    assert book.status_of("o-1") == OrderStatus.PARTIAL_FILLED
    assert book._orders["o-1"]["filled_qty"] == 100

    book.apply_event("o-1", "filled", {"filled_qty": 100, "price": 10.1}, ts=3)
    assert book.status_of("o-1") == OrderStatus.FILLED
    assert book._orders["o-1"]["filled_qty"] == 200


def test_order_book_illegal_transition_event():
    """apply 非法迁移事件（PENDING→FILLED）→ ValueError。"""
    book = OrderBook()
    book.register("o-1", "c-1")

    with pytest.raises(ValueError):
        book.apply_event("o-1", "filled", {"filled_qty": 200, "price": 10.0}, ts=1)


# ---------------------------------------------------------------------------
# OrderBook.replay：从 order_event 表重放恢复（§4.6.2 幂等可恢复）
# ---------------------------------------------------------------------------


def test_order_book_replay(sqlite):
    """order_event 表多条事件 → replay 后状态为最终态、filled_qty 累积正确。

    事件序：
      o-1: submitted → partial_filled(100) → filled(100)   → FILLED, 200
      o-2: submitted → cancelled                            → CANCELLED
    """
    # 直接写 order_event 行（绕过 OrderBook，模拟"既有库已落账"场景）
    rows = [
        ("e-1", "o-1", "b-1", "submitted", json.dumps({"broker_order_id": "b-1"}), 1),
        ("e-2", "o-1", "b-1", "partial_filled",
         json.dumps({"filled_qty": 100, "price": 10.0}), 2),
        ("e-3", "o-1", "b-1", "filled",
         json.dumps({"filled_qty": 100, "price": 10.1}), 3),
        ("e-4", "o-2", "b-2", "submitted", json.dumps({"broker_order_id": "b-2"}), 4),
        ("e-5", "o-2", "b-2", "cancelled", json.dumps({}), 5),
    ]
    for r in rows:
        done = sqlite.execute(
            "INSERT INTO order_event(event_id, order_id, broker_order_id, "
            "event_type, payload, ts) VALUES(?,?,?,?,?,?)",
            r,
        )
        done.wait(2)
    sqlite.flush()

    book = OrderBook()
    book.replay(sqlite)

    assert book.status_of("o-1") == OrderStatus.FILLED
    assert book._orders["o-1"]["filled_qty"] == 200
    assert book.status_of("o-2") == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Broker Protocol 结构（§4.6.2）
# ---------------------------------------------------------------------------


def test_broker_protocol_structure():
    """Broker Protocol 暴露：is_synchronous + place/cancel/status/positions/
    account/on_fill 六方法。"""
    attrs = set(Broker.__dict__.keys()) | set(getattr(Broker, "__annotations__", {}))
    for method in ("place", "cancel", "status", "positions", "account", "on_fill"):
        assert method in attrs, f"Broker 缺方法 {method}"
    assert "is_synchronous" in getattr(Broker, "__annotations__", {})
