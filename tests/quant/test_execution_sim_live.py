"""SimBrokerLive 模拟实盘路径测试（设计 v0.5 §4.6.2）。

覆盖 on_fill 异步回调作三态统一成交入口的同步路径（SimBroker is_synchronous=True）：
- place 立即撮合（复用 M1 SimBroker.match）+ on_fill 回调通知
- 撮合结果与 M1 SimBroker.match 一致（复用而非重写）
- T+N / 持仓更新 / 未设 bar 报错

TDD：本文件先于 sim_broker_live.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant.backtest.sim_broker import BarSnapshot, Order, SimBroker
from quant.execution.broker import OrderStatus
from quant.execution.sim_broker_live import SimBrokerLive

# rule_json 种子：沪市主板（tick0.01 / 涨跌停0.10 / T+1 / min_buy100 / lot100 / fees）
RULE_JSON = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
    "min_buy": 100,
    "lot_increment": 100,
    "fees": {
        "stamp": {"value": 0.0005, "_confidence": "provisional"},
        "transfer": {"value": 0.00001, "_confidence": "provisional"},
        "commission": {"value": None, "_confidence": "provisional"},
        "exchange": {"value": None, "_confidence": "provisional"},
    },
}


def _bar(open_=10.0, high=10.2, low=9.8, close=10.1, volume=100_000.0,
         limit_up=11.0, limit_down=9.0) -> BarSnapshot:
    """构造当日 bar 快照。"""
    return BarSnapshot(open=open_, high=high, low=low, close=close,
                       volume=volume, limit_up=limit_up, limit_down=limit_down)


def _rule_fn():
    """返回当前生效 rule_json 的函数（模拟 TradingRuleProvider 取数）。"""
    return RULE_JSON


# ---------------------------------------------------------------- 同步立即撮合

def test_place_synchronous_fills_immediately():
    """set_bar + place 限价买 → 立即撮合，status=FILLED。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    broker_id = broker.place(order, client_order_id="c1")

    assert broker_id == "c1"
    assert broker.status("c1") == OrderStatus.FILLED


# ---------------------------------------------------------------- on_fill 同步回调

def test_on_fill_callback_invoked_sync():
    """注册 on_fill 回调，place 成交 → 回调以 FillResult 被调用。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    received = []
    broker.on_fill(lambda fill: received.append(fill))
    broker.place(order, client_order_id="c1")

    assert len(received) == 1
    fill = received[0]
    assert fill.filled is True
    assert fill.fill_price == pytest.approx(10.00)
    assert fill.fill_qty == 100


# ---------------------------------------------------------------- on_fill 经 loop 异步派发

def test_on_fill_callback_via_loop():
    """bind loop 后，place 成交 → loop.call_soon_threadsafe(cb, fill) 被调。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    loop = MagicMock()
    broker.bind_loop(loop)
    broker.place(order, client_order_id="c1")

    loop.call_soon_threadsafe.assert_called_once()
    cb, fill = loop.call_soon_threadsafe.call_args.args
    assert callable(cb)
    assert fill.filled is True
    assert fill.fill_qty == 100


# ---------------------------------------------------------------- 持仓更新

def test_position_updated_after_fill():
    """买 100 股 → positions[symbol] += 100。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    broker.place(order, client_order_id="c1")

    assert broker.positions().get("600000") == 100


# ---------------------------------------------------------------- 复用 M1 SimBroker.match

def test_reuses_m1_simbroker_matching():
    """同 order+bar+rule，SimBrokerLive.place 与 M1 SimBroker.match 结果一致。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    broker.place(order, client_order_id="c1")
    live_fill = broker.status("c1") and broker._fills["c1"]

    m1 = SimBroker()
    expected = m1.match(order, _bar(low=9.8, high=10.2), RULE_JSON)

    assert live_fill.fill_price == pytest.approx(expected.fill_price)
    assert live_fill.fill_qty == expected.fill_qty
    assert live_fill.cost.fill_price == pytest.approx(expected.cost.fill_price)
    assert live_fill.cost.commission == pytest.approx(expected.cost.commission)


# ---------------------------------------------------------------- T+N

def test_tplusn_respected():
    """卖出 position_qty=0 → T+1 不成交（复用 M1 规则）。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    broker.set_bar(_bar(low=9.8, high=10.2))
    broker.set_positions({"600000": 0})
    order = Order(symbol="600000", side="sell", qty=100, order_type="limit", price=10.00)

    broker.place(order, client_order_id="c1")

    assert broker.status("c1") != OrderStatus.FILLED


# ---------------------------------------------------------------- 前置校验

def test_no_bar_raises():
    """未 set_bar 时 place → RuntimeError（缺撮合依据）。"""
    broker = SimBrokerLive(rule_json_fn=_rule_fn)
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)

    with pytest.raises(RuntimeError):
        broker.place(order, client_order_id="c1")
