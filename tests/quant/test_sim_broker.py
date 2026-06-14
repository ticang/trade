"""SimBroker 撮合测试（设计 v0.5 §4.7.1/§4.7.3）。

覆盖 A 股 bar 级事件驱动撮合的关键分支：
- 限价成交（区间内触及 / 未触及 / 开盘即穿透）
- 市价成交（按 bar.open）
- 一字板封死（涨停买不进 / 跌停卖不出）
- 量比限制（成交不超当日量比例）
- T+N（T+1 不允许日内卖空，需持仓）
- 申报合法性（tick 网格 / lot 手数）
- 摩擦成本（成交后 cost 由 FrictionModel.apply 计算）

注：无 L2 盘口，成交按 bar 级保守概率模型，结果标 bar_level_simulated。
"""
from __future__ import annotations

import pytest

from quant.backtest.friction import FrictionModel
from quant.backtest.sim_broker import BarSnapshot, FillResult, Order, SimBroker

# rule_json 种子：沪市主板股票（M0.5 rules_v1.yaml sse_main_stock）
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


# ---------------------------------------------------------------- 限价买入成交判定

def test_limit_buy_filled_when_price_in_range():
    """限价买单，价格落在 bar 区间内 → 按申报价成交。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)
    res = broker.match(order, _bar(low=9.8, high=10.2), RULE_JSON)
    assert res.filled is True
    assert res.fill_price == pytest.approx(10.00)
    assert res.fill_qty == 100
    assert res.reason == "ok"


def test_limit_buy_unreached():
    """限价买 9.50，bar 最低 9.8 → 价格未触及，不成交。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=9.50)
    res = broker.match(order, _bar(low=9.8, high=10.2), RULE_JSON)
    assert res.filled is False
    assert res.reason == "limit_unreached"


def test_limit_buy_gapped_open():
    """限价买 10.50，开盘 10.2 已穿透买价 → 按开盘价成交。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.50)
    bar = _bar(open_=10.2, high=10.3, low=10.1, close=10.25)
    res = broker.match(order, bar, RULE_JSON)
    assert res.filled is True
    assert res.fill_price == pytest.approx(10.2)  # bar.open（摩擦前）
    assert res.reason == "ok"


# ---------------------------------------------------------------- 市价

def test_market_buy_fills_at_open():
    """市价买单 → 按 bar.open 成交。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=100, order_type="market")
    bar = _bar(open_=10.2)
    res = broker.match(order, bar, RULE_JSON)
    assert res.filled is True
    assert res.fill_price == pytest.approx(10.2)
    assert res.fill_qty == 100
    assert res.reason == "ok"


# ---------------------------------------------------------------- 一字板封死

def test_limit_up_sealed_no_buy():
    """涨停一字板封死（开/高/低/收=涨停价）→ 买不进。"""
    broker = SimBroker()
    bar = _bar(open_=11.0, high=11.0, low=11.0, close=11.0,
               limit_up=11.0, limit_down=9.0)
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=11.0)
    res = broker.match(order, bar, RULE_JSON)
    assert res.filled is False
    assert res.reason == "limit_up_sealed"


def test_limit_down_sealed_no_sell():
    """跌停一字板封死 → 卖不出。"""
    broker = SimBroker()
    bar = _bar(open_=9.0, high=9.0, low=9.0, close=9.0,
               limit_up=11.0, limit_down=9.0)
    order = Order(symbol="600000", side="sell", qty=100, order_type="limit", price=9.0)
    res = broker.match(order, bar, RULE_JSON, position_qty=100)
    assert res.filled is False
    assert res.reason == "limit_down_sealed"


# ---------------------------------------------------------------- 量比限制

def test_volume_ratio_caps_qty():
    """申报量远超当日成交量 → 成交量被量比封顶，封顶后不足 min_buy → volume_exceeded。"""
    broker = SimBroker(volume_ratio=0.1)
    order = Order(symbol="600000", side="buy", qty=10_000, order_type="limit", price=10.00)
    # 当日量 1000，量比 0.1 → 最多成交 100 股
    bar = _bar(low=9.8, high=10.2, volume=1_000.0)
    res = broker.match(order, bar, RULE_JSON)
    assert res.filled is True
    assert res.fill_qty == 100
    assert res.reason == "ok"

    # 当日量过小，量比封顶后不足 min_buy → 不成交
    bar2 = _bar(low=9.8, high=10.2, volume=500.0)
    res2 = broker.match(order, bar2, RULE_JSON)
    assert res2.filled is False
    assert res2.reason == "volume_exceeded"


# ---------------------------------------------------------------- T+N

def test_tplusn_sell_needs_position():
    """T+1：无持仓卖空 → no_position_tplusn；有持仓可卖。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="sell", qty=100, order_type="limit", price=10.00)
    bar = _bar(low=9.8, high=10.2)

    # 无持仓
    res0 = broker.match(order, bar, RULE_JSON, position_qty=0)
    assert res0.filled is False
    assert res0.reason == "no_position_tplusn"

    # 有持仓
    res1 = broker.match(order, bar, RULE_JSON, position_qty=100)
    assert res1.filled is True
    assert res1.fill_qty == 100
    assert res1.reason == "ok"


# ---------------------------------------------------------------- 申报合法性

def test_illegal_tick():
    """限价单申报价不在 tick 网格（10.005，tick 0.01）→ illegal_tick。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.005)
    res = broker.match(order, _bar(), RULE_JSON)
    assert res.filled is False
    assert res.reason == "illegal_tick"


def test_illegal_lot_buy():
    """买单数量非 lot_increment 倍数（150，increment 100）→ illegal_lot。"""
    broker = SimBroker()
    order = Order(symbol="600000", side="buy", qty=150, order_type="limit", price=10.00)
    res = broker.match(order, _bar(), RULE_JSON)
    assert res.filled is False
    assert res.reason == "illegal_lot"


# ---------------------------------------------------------------- 摩擦成本

def test_friction_applied_on_fill():
    """成交后 cost 来自 FrictionModel.apply（印花税仅卖出，过户费双边等）。"""
    friction = FrictionModel()
    broker = SimBroker(friction=friction)
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)
    res = broker.match(order, _bar(low=9.8, high=10.2), RULE_JSON)
    assert res.filled is True
    assert res.cost is not None
    # 摩擦前成交价 10.00，经滑点后 fill_price > 10（买入上浮）
    assert res.cost.fill_price > 10.00
    # 与 FrictionModel.apply 直接计算一致
    expected = friction.apply("buy", 10.00, 100, RULE_JSON["fees"])
    assert res.cost.fill_price == pytest.approx(expected.fill_price)
    assert res.cost.commission == pytest.approx(expected.commission)
    # 买入无印花税
    assert res.cost.stamp == 0.0
