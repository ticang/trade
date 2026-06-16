"""SimBrokerLive：Broker 的模拟实盘路径（设计 v0.5 §4.6.2）。

on_fill 异步回调作三态统一成交入口：SimBroker（同步）/ QmtBroker（异步）回报
均经 on_fill 通知策略层，规避"同 bar 内查 status 决策"反模式与同步/异步阻抗。

本类 is_synchronous=True：place 立即撮合，但仍经 on_fill 回调通知（统一入口）。
撮合逻辑复用 M1 SimBroker.match（摩擦/A 股规则），不重写。当前 bar 由 set_bar
注入（实盘每根 bar 由网关更新）。
"""
from __future__ import annotations

from typing import Callable

from quant.backtest.sim_broker import BarSnapshot, FillResult, Order, SimBroker
from quant.execution.broker import OrderStatus


class SimBrokerLive:
    """Broker 的模拟实盘路径。

    is_synchronous=True：place 立即撮合 + on_fill 回调。复用 M1 SimBroker.match。
    当前 bar 由 set_bar 注入（live 每根 bar 网关更新）。
    """

    is_synchronous = True

    def __init__(self, rule_json_fn: Callable[[], dict], friction=None,
                 volume_ratio: float = 0.1) -> None:
        self._sim = SimBroker(friction, volume_ratio)
        self._rule_json_fn = rule_json_fn
        self._bar: BarSnapshot | None = None
        self._positions: dict[str, int] = {}      # symbol -> qty
        self._fills: dict[str, FillResult] = {}   # order_id -> fill
        self._on_fill_cb: Callable[[FillResult], None] | None = None
        self._loop = None

    def bind_loop(self, loop) -> None:
        """绑定事件循环（异步派发 on_fill 回调）。"""
        self._loop = loop

    def set_bar(self, bar: BarSnapshot) -> None:
        """注入当前 bar（实盘每根 bar 网关更新）。"""
        self._bar = bar

    def set_positions(self, positions: dict[str, int]) -> None:
        """注入持仓快照（T+N 卖出校验依据）。"""
        self._positions = dict(positions)

    def on_fill(self, callback: Callable[[FillResult], None]) -> None:
        """注册成交回报回调（三态统一入口）。"""
        self._on_fill_cb = callback

    def place(self, order: Order, client_order_id: str) -> str:
        """立即撮合：require bar set + rule。

        match → 若 filled：更新 positions、存 fill、触发 on_fill 回调
        （有 loop：loop.call_soon_threadsafe(cb, fill)；否则同步 cb(fill)）。
        返回 client_order_id（模拟 broker id）。
        """
        if self._bar is None:
            raise RuntimeError("bar 未注入：place 前须 set_bar")

        rule_json = self._rule_json_fn()
        position_qty = self._positions.get(order.symbol, 0)
        fill = self._sim.match(order, self._bar, rule_json, position_qty)

        if fill.filled:
            # 持仓更新：买加卖减
            delta = fill.fill_qty if order.side == "buy" else -fill.fill_qty
            self._positions[order.symbol] = self._positions.get(order.symbol, 0) + delta
            self._fills[client_order_id] = fill

            # 经 on_fill 统一入口通知：绑 loop 走异步派发，否则同步回调
            # 未注册回调时用 noop 占位，保证 loop 路径仍被触发（异步语义统一）
            cb = self._on_fill_cb or _noop
            if self._loop is not None:
                self._loop.call_soon_threadsafe(cb, fill)
            else:
                cb(fill)

        return client_order_id

    def cancel(self, order_id: str) -> None:
        """模拟立即成交，cancel 无操作。"""

    def status(self, order_id: str) -> OrderStatus:
        """order_id 在 _fills → FILLED；否则 PENDING。"""
        if order_id in self._fills:
            return OrderStatus.FILLED
        return OrderStatus.PENDING

    def positions(self) -> dict[str, int]:
        """返回持仓快照副本。"""
        return dict(self._positions)

    def fills(self) -> dict[str, FillResult]:
        """返回成交回报快照副本，供日终对账读取。"""
        return dict(self._fills)

    def account(self) -> dict:
        """账户资金（简化）。"""
        return {"cash": 0.0}


def _noop(_fill: FillResult) -> None:
    """未注册回调时的占位（保持 loop 异步派发语义）。"""
