"""RiskEngine 基础层测试（设计 v0.5 §4.5）。

覆盖风控基础层（全档）关键校验：
- 涨跌停/停牌/ST/退市过滤
- 申报价格 tick / 数量 lot 合法性
- 单票仓位上限 / 总仓位上限 / 单笔金额上限
- 单仓位止损 / 止盈（持仓级提示）

注：风控在撮合前做最终合法性校验；止损止盈针对已有持仓做提示性违规。
"""
from __future__ import annotations

import pytest

from quant.backtest.sim_broker import BarSnapshot, Order
from quant.risk.engine import (
    PositionInfo,
    RiskConfig,
    RiskEngine,
    RiskResult,
    RiskViolation,
)

# rule_json 种子：tick 0.01 / min_buy 100 / lot_increment 100
RULE_JSON = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
    "min_buy": 100,
    "lot_increment": 100,
    "fees": {},
}


def _rule_json_fn(symbol: str) -> dict:
    """rule_json_fn：忽略 symbol，统一返回 RULE_JSON。"""
    return RULE_JSON


def _bar(open_=10.0, high=10.2, low=9.8, close=10.1, volume=100_000.0,
         limit_up=11.0, limit_down=9.0) -> BarSnapshot:
    """构造当日 bar 快照。"""
    return BarSnapshot(open=open_, high=high, low=low, close=close,
                       volume=volume, limit_up=limit_up, limit_down=limit_down)


def _bar_today(symbol: str = "600000") -> dict[str, BarSnapshot]:
    """构造 bars_today 字典。"""
    return {symbol: _bar()}


def test_clean_order_passes() -> None:
    """合法小单：tick 对齐、lot 对齐、仓位远低于上限 → passed。"""
    engine = RiskEngine()
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00)
    result = engine.check(
        orders=[order],
        positions=[],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today=_bar_today(),
    )
    assert result.passed is True
    assert result.violations == []


def test_max_single_rejected() -> None:
    """单笔买入使单票仓位占比 >10% → max_single。

    total_equity=1_000_000，买入 100 股 @100 = 100_000，恰好 10%；
    稍高于 10% 触发违例。
    """
    engine = RiskEngine()
    # 单价抬高使名义价值 >10%：100 股 @110 = 11_000，占总权益 1_000_000 的 1.1%；
    # 改大单量：1000 股 @110 = 110_000 = 11% → 违
    order = Order(symbol="600000", side="buy", qty=1000, order_type="limit", price=110.00)
    result = engine.check(
        orders=[order],
        positions=[],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today={"600000": _bar(open_=110.0, high=110.0, low=110.0, close=110.0,
                                   limit_up=121.0, limit_down=99.0)},
    )
    assert result.passed is False
    assert any(v.reason == "max_single" for v in result.violations)


def test_max_total_rejected() -> None:
    """已有持仓逼近 95%，再买 → 总仓位 >95% → max_total。

    total_equity=1_000_000，已有持仓市值 940_000（94%），再买 100 股 @200 = 20_000
    → 总仓位 96_0000 / 1_000_000 = 96% > 95%。
    """
    engine = RiskEngine()
    pos = PositionInfo(symbol="600000", qty=10_000, avg_cost=94.0, last=94.0)
    order = Order(symbol="600001", side="buy", qty=100, order_type="limit", price=200.00)
    result = engine.check(
        orders=[order],
        positions=[pos],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today={
            "600000": _bar(),
            "600001": _bar(open_=200.0, high=200.0, low=200.0, close=200.0,
                           limit_up=220.0, limit_down=180.0),
        },
    )
    assert result.passed is False
    assert any(v.reason == "max_total" for v in result.violations)


def test_limit_up_filtered() -> None:
    """买封涨停股（low==high==limit_up）→ limit_up_filtered。"""
    engine = RiskEngine()
    # 一字涨停板：开/高/低/收=涨停价
    bar = _bar(open_=11.0, high=11.0, low=11.0, close=11.0, limit_up=11.0, limit_down=9.0)
    order = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=11.00)
    result = engine.check(
        orders=[order],
        positions=[],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today={"600000": bar},
    )
    assert result.passed is False
    assert any(v.reason == "limit_up_filtered" for v in result.violations)


def test_suspend_st_delist_filtered() -> None:
    """flags 命中 suspended/st/delisted → 对应 reason。"""
    engine = RiskEngine()
    flags = {
        "600000": {"suspended": True, "st": False, "delisted": False},
        "600001": {"suspended": False, "st": True, "delisted": False},
        "600002": {"suspended": False, "st": False, "delisted": True},
    }
    orders = [
        Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.00),
        Order(symbol="600001", side="buy", qty=100, order_type="limit", price=10.00),
        Order(symbol="600002", side="buy", qty=100, order_type="limit", price=10.00),
    ]
    result = engine.check(
        orders=orders,
        positions=[],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today=_bar_today(),
        flags=flags,
    )
    assert result.passed is False
    reasons = {v.reason for v in result.violations}
    assert "suspend_filtered" in reasons
    assert "st_filtered" in reasons
    assert "delist_filtered" in reasons


def test_illegal_tick_lot() -> None:
    """tick 不对齐 → illegal_tick；lot 不对齐 → illegal_lot。"""
    engine = RiskEngine()
    # tick 0.01，价格 10.005 不在网格
    bad_tick = Order(symbol="600000", side="buy", qty=100, order_type="limit", price=10.005)
    # lot_increment 100，数量 150 非倍数
    bad_lot = Order(symbol="600001", side="buy", qty=150, order_type="limit", price=10.00)
    result = engine.check(
        orders=[bad_tick, bad_lot],
        positions=[],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today={"600000": _bar(), "600001": _bar()},
    )
    assert result.passed is False
    reasons = {v.reason for v in result.violations}
    assert "illegal_tick" in reasons
    assert "illegal_lot" in reasons


def test_max_order_value() -> None:
    """单笔名义价值 >500_000 → max_order_value。

    5000 股 @110 = 550_000。
    """
    engine = RiskEngine()
    order = Order(symbol="600000", side="buy", qty=5000, order_type="limit", price=110.00)
    result = engine.check(
        orders=[order],
        positions=[],
        total_equity=10_000_000.0,  # 抬高权益避免 max_single/max_total 误判
        rule_json_fn=_rule_json_fn,
        bars_today={"600000": _bar(open_=110.0, high=110.0, low=110.0, close=110.0,
                                   limit_up=121.0, limit_down=99.0)},
    )
    assert result.passed is False
    assert any(v.reason == "max_order_value" for v in result.violations)


def test_stop_loss_triggered() -> None:
    """持仓浮亏 -15%（超 -10% 止损）→ stop_loss_triggered（应平仓提示）。"""
    engine = RiskEngine()
    # avg_cost=100，last=85 → -15%
    pos = PositionInfo(symbol="600000", qty=1000, avg_cost=100.0, last=85.0)
    result = engine.check(
        orders=[],
        positions=[pos],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today=_bar_today(),
    )
    assert result.passed is False
    assert any(v.reason == "stop_loss_triggered" for v in result.violations)


def test_take_profit_triggered() -> None:
    """持仓浮盈 +25%（超 +20% 止盈）→ take_profit_triggered（应平仓提示）。"""
    engine = RiskEngine()
    # avg_cost=100，last=125 → +25%
    pos = PositionInfo(symbol="600000", qty=1000, avg_cost=100.0, last=125.0)
    result = engine.check(
        orders=[],
        positions=[pos],
        total_equity=1_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today=_bar_today(),
    )
    assert result.passed is False
    assert any(v.reason == "take_profit_triggered" for v in result.violations)


def test_multiple_violations_collected() -> None:
    """一单多违：tick 不合法 + lot 不合法 + 超单笔金额 → violations 收集多条。

    构造：tick 不对齐、lot 不对齐、名义价值超 500_000。
    """
    engine = RiskEngine()
    # 价格 110.005 tick 不合法，数量 50 < min_buy，名义价 50*110.005=5500.25 远低上限；
    # 为同时触发 max_order_value，改大单量但 lot 必须违 → 用 150 手（lot 不对齐）+ 高价
    # 150 * 4000.005 = 600_000.75 > 500_000；tick 4000.005 不在网格；150 非 100 倍数
    order = Order(symbol="600000", side="buy", qty=150, order_type="limit", price=4000.005)
    result = engine.check(
        orders=[order],
        positions=[],
        total_equity=10_000_000.0,
        rule_json_fn=_rule_json_fn,
        bars_today={"600000": _bar(open_=4000.0, high=4000.0, low=4000.0, close=4000.0,
                                   limit_up=4400.0, limit_down=3600.0)},
    )
    assert result.passed is False
    reasons = [v.reason for v in result.violations]
    assert "illegal_tick" in reasons
    assert "illegal_lot" in reasons
    assert "max_order_value" in reasons
    # 多违被收集（至少 3 条）
    assert len(result.violations) >= 3
