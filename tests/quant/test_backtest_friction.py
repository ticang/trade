"""交易摩擦模型测试（设计 v0.5 §4.7.2）。

覆盖 FrictionModel.apply 的成本拆分：
- 印花税仅卖出收取；过户费双边
- 滑点方向（买入成交价上浮、卖出成交价下浮）
- 佣金双边（取 FrictionConfig.commission_rate）
- provisional 费用记 flag（不阻断回测）
- rule_fees 缺项 → 该费 0、不记 flag
- 总成本占成交额比例合理
"""
from __future__ import annotations

import pytest

from quant.backtest.friction import FillCost, FrictionConfig, FrictionModel

# rule_json.fees 种子（M0.5 rules_v1.yaml）：stamp/transfer provisional，commission/exchange 未定
RULE_FEES = {
    "stamp": {"value": 0.0005, "_confidence": "provisional"},
    "transfer": {"value": 0.00001, "_confidence": "provisional"},
    "commission": {"value": None, "_confidence": "provisional"},
    "exchange": {"value": None, "_confidence": "provisional"},
}


def test_buy_no_stamp():
    """买入不收印花税。"""
    m = FrictionModel()
    fc = m.apply("buy", 10.0, 1000, RULE_FEES)
    assert fc.stamp == 0.0


def test_sell_has_stamp():
    """卖出按 stamp_rate 收印花税 = fill_price*qty*0.0005。"""
    m = FrictionModel()
    fc = m.apply("sell", 10.0, 1000, RULE_FEES)
    # fill_price 受滑点影响略低于 10，用近似
    assert fc.stamp == pytest.approx(fc.fill_price * 1000 * 0.0005)


def test_slippage_direction():
    """买入成交价上浮、卖出成交价下浮；滑点成本为正。"""
    m = FrictionModel()
    buy = m.apply("buy", 10.0, 1000, RULE_FEES)
    sell = m.apply("sell", 10.0, 1000, RULE_FEES)
    assert buy.fill_price > 10.0
    assert sell.fill_price < 10.0
    assert buy.slippage_cost > 0
    assert sell.slippage_cost > 0


def test_commission_both_sides():
    """佣金双边收取 = fill_price*qty*commission_rate。"""
    m = FrictionModel()
    for side in ("buy", "sell"):
        fc = m.apply(side, 10.0, 1000, RULE_FEES)
        assert fc.commission == pytest.approx(
            fc.fill_price * 1000 * m.config.commission_rate
        )


def test_transfer_both_sides():
    """过户费双边收取 = fill_price*qty*transfer_rate。"""
    m = FrictionModel()
    for side in ("buy", "sell"):
        fc = m.apply(side, 10.0, 1000, RULE_FEES)
        assert fc.transfer == pytest.approx(fc.fill_price * 1000 * 0.00001)


def test_provisional_flags_recorded():
    """rule_fees 各明细 _confidence=provisional → 记 flag（不阻断）。"""
    m = FrictionModel()
    # 卖出触发印花税与过户费，两项均 provisional
    fc = m.apply("sell", 10.0, 1000, RULE_FEES)
    assert "stamp" in fc.provisional_flags
    assert "transfer" in fc.provisional_flags


def test_missing_fees_zero():
    """rule_fees=None：印花税/过户费为 0，佣金用 config 默认。"""
    m = FrictionModel()
    fc = m.apply("buy", 10.0, 1000, rule_fees=None)
    assert fc.stamp == 0.0
    assert fc.transfer == 0.0
    assert fc.commission == pytest.approx(
        fc.fill_price * 1000 * m.config.commission_rate
    )
    assert fc.provisional_flags == []


def test_total_cost_reasonable():
    """卖出总成本（佣金+印花税+过户费+滑点）占成交额比例 < 1%。"""
    m = FrictionModel()
    fc = m.apply("sell", 10.0, 1000, RULE_FEES)
    notional = fc.fill_price * 1000
    total = fc.commission + fc.stamp + fc.transfer + fc.slippage_cost
    assert total / notional < 0.01
