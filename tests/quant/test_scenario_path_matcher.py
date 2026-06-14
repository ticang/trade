"""路径过撮合测试（M5a §4.8.2 情景引擎 Task 4）。

A 股规则在路径评估层生效，而非塞进价格过程：路径价格保持连续，
涨跌停截断 / 一字板判定 / T+N 标注在评估时施加。

rule_json 种子：沪市主板股票（M0.5 rules_v1.yaml sse_main_stock）。
"""
from __future__ import annotations

import numpy as np
import pytest

from quant.scenario.path_matcher import (
    apply_limit_truncation,
    evaluate_path_pnl,
    match_scenario_path,
    path_to_bar,
)

# rule_json 种子：涨跌停 ±10%，T+1
RULE_JSON = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
}


# ---------------------------------------------------------------- 涨跌停截断

def test_limit_truncation_up():
    """价格超涨停价 → 截断到涨停价（prev_close=10，涨停=11）。"""
    prices = np.array([10.0, 10.5, 11.5, 12.0])
    out = apply_limit_truncation(prices, prev_close=10.0,
                                 limit_up=0.10, limit_down=0.10)
    assert out[2] == pytest.approx(11.0)
    assert out[3] == pytest.approx(11.0)
    assert out[0] == pytest.approx(10.0)
    assert out[1] == pytest.approx(10.5)


def test_limit_truncation_down():
    """跌破跌停价 → 截断到跌停价（prev_close=10，跌停=9）。"""
    prices = np.array([10.0, 9.5, 8.5, 8.0])
    out = apply_limit_truncation(prices, prev_close=10.0,
                                 limit_up=0.10, limit_down=0.10)
    assert out[2] == pytest.approx(9.0)
    assert out[3] == pytest.approx(9.0)
    assert out[1] == pytest.approx(9.5)


def test_limit_truncation_within():
    """区间内不截断。"""
    prices = np.array([10.0, 10.5, 9.5, 10.2])
    out = apply_limit_truncation(prices, prev_close=10.0,
                                 limit_up=0.10, limit_down=0.10)
    np.testing.assert_array_almost_equal(out, prices)


# ---------------------------------------------------------------- 路径 → OHLC bar

def test_path_to_bar_ohlc():
    """路径价格序列 → bar 序列：open=prev_close，high/low/close 累积正确。"""
    # 路径：10 → 10.5 → 9.8 → 10.2（前收=10）
    path = np.array([10.0, 10.5, 9.8, 10.2])
    bars = path_to_bar(path, prev_close=10.0)
    assert len(bars) == 4
    # 第 0 个点：open=prev_close=10，close=10.0，high=10.0，low=10.0
    assert bars[0].open == pytest.approx(10.0)
    assert bars[0].close == pytest.approx(10.0)
    # 最后一个点：open=prev_close，high=max(10,10.5,9.8,10.2)=10.5，low=9.8，close=10.2
    last = bars[-1]
    assert last.open == pytest.approx(10.0)
    assert last.high == pytest.approx(10.5)
    assert last.low == pytest.approx(9.8)
    assert last.close == pytest.approx(10.2)
    # 涨跌停价字段
    assert hasattr(last, "limit_up")
    assert hasattr(last, "limit_down")


# ---------------------------------------------------------------- 情景路径撮合

def test_match_buy_limit_up_sealed():
    """路径收盘=涨停价 → 买：limit_up 一字板，feasible_price=None。

    收盘价等于涨停价即视为封板不可买。此处路径恰落在涨停边界（未超界，
    truncated=False），但收盘=涨停价触发一字板判定。
    """
    # prev_close=10，路径=涨停价=11（封板但未越界）
    path_returns = np.array([0.10, 0.10, 0.10])
    res = match_scenario_path(path_returns, prev_close=10.0,
                              rule_json=RULE_JSON, side="buy")
    assert res["limit_hit"] == "limit_up"
    assert res["feasible_price"] is None


def test_match_buy_limit_up_sealed_after_truncation():
    """路径曾超涨停被截断，收盘=涨停价 → 一字板，feasible_price=None，truncated=True。"""
    # prev_close=10，路径 +15% → +15%（越涨停被截断到 11）
    path_returns = np.array([0.15, 0.15])
    res = match_scenario_path(path_returns, prev_close=10.0,
                              rule_json=RULE_JSON, side="buy")
    assert res["truncated"] is True
    assert res["limit_hit"] == "limit_up"
    assert res["feasible_price"] is None


def test_match_normal_fill():
    """路径收盘在区间内 → feasible_price=截断后收盘价，limit_hit=None。"""
    # 路径收益 [0.01, 0.02, 0.015]，收盘价 = 10*1.015 = 10.15
    path_returns = np.array([0.01, 0.02, 0.015])
    res = match_scenario_path(path_returns, prev_close=10.0,
                              rule_json=RULE_JSON, side="buy")
    assert res["limit_hit"] is None
    assert res["truncated"] is False
    assert res["feasible_price"] == pytest.approx(10.15)


def test_match_sell_limit_down_sealed():
    """路径收盘=跌停价 → 卖：limit_down 一字板，feasible_price=None。"""
    path_returns = np.array([-0.10, -0.10, -0.10])
    res = match_scenario_path(path_returns, prev_close=10.0,
                              rule_json=RULE_JSON, side="sell")
    assert res["limit_hit"] == "limit_down"
    assert res["feasible_price"] is None


def test_match_truncated_but_not_sealed():
    """路径曾超涨停但收盘回落 → 截断发生，但收盘非涨停价 → 可成交。"""
    # 路径：+15% → +5%（过程超涨停被截断，但收盘在区间内）
    path_returns = np.array([0.15, 0.05])
    res = match_scenario_path(path_returns, prev_close=10.0,
                              rule_json=RULE_JSON, side="buy")
    assert res["truncated"] is True
    assert res["limit_hit"] is None
    assert res["feasible_price"] == pytest.approx(10.5)


# ---------------------------------------------------------------- 路径盈亏评估

def test_evaluate_pnl_long():
    """持仓多 + 路径涨 → PnL>0；跌 → PnL<0；截断压制极端 PnL。"""
    # 涨 5%（区间内）：100 股 × 0.5 元 = +50
    pos = {"qty": 100, "side": "long"}
    pnl_up = evaluate_path_pnl(np.array([0.0, 0.05]), pos, prev_close=10.0,
                                rule_json=RULE_JSON)
    assert pnl_up == pytest.approx(50.0)

    # 跌 5%：-50
    pnl_down = evaluate_path_pnl(np.array([0.0, -0.05]), pos, prev_close=10.0,
                                 rule_json=RULE_JSON)
    assert pnl_down == pytest.approx(-50.0)

    # 截断影响：路径涨 50%，被截断到 +10%；若无截断 PnL=500，截断后 PnL=100
    pnl_trunc = evaluate_path_pnl(np.array([0.0, 0.50]), pos, prev_close=10.0,
                                  rule_json=RULE_JSON)
    assert pnl_trunc == pytest.approx(100.0)  # 截断到 10%


def test_evaluate_pnl_short():
    """持仓空 + 路径跌 → PnL>0。"""
    pos = {"qty": 100, "side": "short"}
    pnl = evaluate_path_pnl(np.array([0.0, -0.05]), pos, prev_close=10.0,
                            rule_json=RULE_JSON)
    assert pnl == pytest.approx(50.0)


# ---------------------------------------------------------------- T+N 标注

def test_tplusn_flag():
    """settlement_T=1 → tplusn_ok 字段返回 T 值（调用方据持仓判定）。"""
    res = match_scenario_path(np.array([0.01]), prev_close=10.0,
                              rule_json=RULE_JSON, side="sell")
    assert res["tplusn_ok"] == 1


def test_tplusn_zero():
    """settlement_T=0 → tplusn_ok=0。"""
    rule_t0 = {**RULE_JSON, "settlement_T": 0}
    res = match_scenario_path(np.array([0.01]), prev_close=10.0,
                              rule_json=rule_t0, side="buy")
    assert res["tplusn_ok"] == 0
