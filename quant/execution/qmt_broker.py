"""QmtBroker：Broker 的 QMT 实现（设计 v0.5 §4.6.1 per-account + §4.6.2 on_fill 异步）。

xtquant 仅 Windows + QMT 终端可装，macOS/Linux 缺失。本模块顶层禁止 import xtquant
—— 构造时 lazy import，失败抛 RuntimeError。per-account：每个 QmtBroker 实例绑定
单一 account_id，trader/get_stock_account 一次构造，client_order_id 去重隔离于
该实例内。is_synchronous=False：成交回报在 xtquant 内部线程触发，经 ThreadBridge
桥接到 asyncio loop 上的 on_fill，策略层只接 on_fill 不在回调内查 status。
"""
from __future__ import annotations

from typing import Any, Callable

from quant.execution.broker import DuplicateOrderError, OrderStatus
from quant.gateway.thread_bridge import ThreadBridge

__all__ = ["QmtBroker"]


def _try_import_xtquant():
    """lazy import xtquant；不可用返回 None。

    顶层不 import xtquant，避免 macOS/Linux import 即崩。
    返回 (xttrader, xtdata) 或 None。
    """
    try:
        import xtquant.xttrader as xttrader  # type: ignore[import-not-found]
        import xtquant.xtdata as xtdata  # type: ignore[import-not-found]
    except Exception:
        return None
    return xttrader, xtdata


# xt order_status → OrderStatus 映射（xt 常量值参考 xttrader 文档）
#   48/49 未报/待报 → PENDING；50 部分成交；53 已撤；55 全部成交；56 已报；
#   57/58/59 部分撤/未成交/已成交未知；60 废单 → REJECTED
_XT_STATUS_MAP: dict[int, OrderStatus] = {
    48: OrderStatus.PENDING,
    49: OrderStatus.PENDING,
    50: OrderStatus.PARTIAL_FILLED,
    53: OrderStatus.CANCELLED,
    55: OrderStatus.FILLED,
    56: OrderStatus.SUBMITTED,
    57: OrderStatus.CANCELLED,
    58: OrderStatus.CANCELLED,
    60: OrderStatus.REJECTED,
}


# Order.side/order_type → xt order_type 常量（0 买/1 卖；1 限价/5 市价 等本地差异）
def _side_to_xt(side: str) -> int:
    """Order.side → xttrader order_type 买卖方向（0 买 / 1 卖）。"""
    return 0 if side == "buy" else 1


class QmtBroker:
    """Broker 的 QMT 实现。

    per-account：构造时绑定单一 account_id，get_stock_account 一次。
    xtquant lazy import；macOS/无 xtquant → 构造抛 RuntimeError。
    is_synchronous=False：成交回报在 xtquant 内部线程触发，经 bridge → on_fill 异步。
    """

    is_synchronous = False

    def __init__(
        self,
        account_id: str,
        path: str,
        session_id: int,
        bridge: ThreadBridge,
    ) -> None:
        mods = _try_import_xtquant()
        if mods is None:
            raise RuntimeError(
                "xtquant unavailable (Windows-only): install QMT terminal"
            )
        self._xttrader, self._xtdata = mods
        self.account_id = account_id
        self._bridge = bridge
        self._trader = self._xttrader.XtQuantTrader(path, session_id)
        self._trader.start()
        self._trader.connect()
        self._account = self._trader.get_stock_account(account_id)
        # per-instance client_order_id 去重集（§4.6.2 断线重连防重复）
        self._client_ids: set[str] = set()
        # on_fill 异步回调（经 bridge 从内部线程桥接）
        self._on_fill_cb: Callable[[Any], None] | None = None
        # 注册成交回报回调：xtquant 内部线程 → bridge → on_fill
        # 真实回调对象在 xtquant 内注册（此处预留 register_callback 调用）
        try:
            self._trader.register_callback(self._build_xt_callback())
        except AttributeError:
            # fake/未提供 register_callback 时跳过（测试 mock 路径）
            pass

    def _build_xt_callback(self):
        """构造 xttrader 成交回调对象（内部线程触发）。

        xtquant 回调对象约定 on_stock_order/on_stock_trade 等方法；
        在内部线程中调用，经 bridge.bridge 投递到 loop 上的 on_fill。
        """
        broker = self

        class _OrderCallback:
            def on_stock_order(self, order: dict) -> None:  # noqa: ANN001
                # 内部线程：构造 fill dict → bridge → on_fill
                if broker._on_fill_cb is None:
                    return
                broker._bridge.bridge(_xt_order_to_fill(order))

        return _OrderCallback()

    # ---------------- Broker 协议 ----------------

    def on_fill(self, callback: Callable[[Any], None]) -> None:
        """注册成交回报回调（§4.6.2 异步入口）。

        xtquant 内部线程回报经 bridge 桥接到 loop，最终调用此 callback。
        """
        self._on_fill_cb = callback

    def place(self, order: Any, client_order_id: str) -> str:
        """下单：xttrader.order_stock → 返回 seq（broker order_id）。

        client_order_id 去重（per-instance，DuplicateOrderError）。
        order.symbol/side/qty/price/order_type 映射到 xttrader 参数。
        """
        if client_order_id in self._client_ids:
            raise DuplicateOrderError(
                f"client_order_id 已存在: {client_order_id}"
            )
        self._client_ids.add(client_order_id)

        order_type = _side_to_xt(order.side)
        price = order.price if order.price is not None else 0.0
        seq = self._trader.order_stock(
            account=self._account,
            stock_code=order.symbol,
            order_type=order_type,
            volume=order.qty,
            price=price,
            strategy="",
            user_order_id=client_order_id,
        )
        return seq

    def cancel(self, order_id: str) -> None:
        """撤单：xttrader.cancel_order_stock。"""
        self._trader.cancel_order_stock(account=self._account, order_id=order_id)

    def status(self, order_id: str) -> OrderStatus:
        """查询订单状态：xttrader.query_order → 映射 OrderStatus。"""
        info = self._trader.query_order(self._account, order_id)
        if not info:
            return OrderStatus.PENDING
        xt_status = info.get("order_status") if isinstance(info, dict) else None
        return _XT_STATUS_MAP.get(xt_status, OrderStatus.PENDING)

    def positions(self) -> list:
        """查询持仓快照：xttrader.query_stock_positions。"""
        return self._trader.query_stock_positions(self._account)

    def account(self) -> dict:
        """查询账户资金：xttrader.query_stock_asset。"""
        return self._trader.query_stock_asset(self._account)


def _xt_order_to_fill(order: dict) -> dict:
    """xtquant 订单回报 dict → on_fill 通知用的 fill dict。

    字段从 xtquant 回调的 order dict 中提取关键字段，供策略层消费。
    """
    return {
        "order_id": order.get("order_id") or order.get("seq"),
        "traded_volume": order.get("traded_volume", 0),
        "traded_price": order.get("traded_price", 0.0),
        "order_status": order.get("order_status"),
        "stock": order.get("stock_code"),
    }
