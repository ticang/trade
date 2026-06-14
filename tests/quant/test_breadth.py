"""市场宽度因子测试（设计 v0.5 §4.1.2 一期诚实化）。

一期差异化定位：交付「因子工程管线 + 市场宽度因子」，不宣称散户情绪反向。
覆盖点：
- limit_up_down_counts：涨跌停家数 + 涨跌家数（per trade_date）
- consecutive_board_height：连板高度（per symbol 最新日）
- seal_rate：封板率（触及涨停中收盘仍封的比例）
- breadth_factor_series：(涨停-跌停)/total 截面时间序列
- 无涨停日 seal_rate 零除保护

TDD：本文件先于 breadth.py 实现编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.factor.factors.breadth import (
    breadth_factor_series,
    consecutive_board_height,
    limit_up_down_counts,
    seal_rate,
)


# ---------------------------------------------------------------------------
# 涨跌停阈值：主板简化 ±10%，忽略板块差异（创业板/科创板 ±20%、ST ±5%）
# 留待 M0.5 规则接入按板块区分。
# ---------------------------------------------------------------------------
LIMIT_PCT = 0.1


def _limit_price(prev_close: float, pct: float = LIMIT_PCT) -> float:
    """涨停价 = round(prev_close * (1+pct), 2)。"""
    return round(prev_close * (1.0 + pct), 2)


def _limit_down_price(prev_close: float, pct: float = LIMIT_PCT) -> float:
    """跌停价 = round(prev_close * (1-pct), 2)。"""
    return round(prev_close * (1.0 - pct), 2)


# ---------------------------------------------------------------------------
# 合成 bars：长格式 trade_date/symbol/open/high/low/close + prev_close 映射
# ---------------------------------------------------------------------------
def _make_bars(records: list[dict]) -> pd.DataFrame:
    """构造长格式 bars DataFrame。records 每行含完整 OHLC。"""
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# test_limit_up_down_counts：2 涨停 + 1 跌停 + 若干普通涨跌
# ---------------------------------------------------------------------------
def test_limit_up_down_counts() -> None:
    # 4 只票，前收均为 10.00 → 涨停价 11.00，跌停价 9.00
    prev_close = pd.Series(
        {"S1": 10.0, "S2": 10.0, "S3": 10.0, "S4": 10.0}, name="prev_close"
    )
    up = _limit_price(10.0)   # 11.00
    down = _limit_down_price(10.0)  # 9.00
    bars = _make_bars(
        [
            # S1 涨停：触及且收盘封板
            dict(trade_date="2024-01-02", symbol="S1", open=10.5, high=up, low=10.4, close=up),
            # S2 涨停
            dict(trade_date="2024-01-02", symbol="S2", open=10.6, high=up, low=10.5, close=up),
            # S3 跌停
            dict(trade_date="2024-01-02", symbol="S3", open=9.5, high=9.5, low=down, close=down),
            # S4 普通下跌（非跌停）
            dict(trade_date="2024-01-02", symbol="S4", open=10.0, high=10.0, low=9.8, close=9.8),
        ]
    )
    counts = limit_up_down_counts(bars, prev_close)
    d = counts.loc["2024-01-02"]
    assert d["limit_up_count"] == 2
    assert d["limit_down_count"] == 1
    # 涨家数 = 涨停 2 + （无其他上涨）= 2；跌家数 = 跌停 1 + 普通下跌 1 = 2
    assert d["advance"] == 2
    assert d["decline"] == 2


# ---------------------------------------------------------------------------
# test_advance_decline：明确涨跌家数（不含涨跌停外的）
# ---------------------------------------------------------------------------
def test_advance_decline() -> None:
    prev_close = pd.Series(
        {"A": 10.0, "B": 10.0, "C": 10.0, "D": 10.0, "E": 10.0}, name="prev_close"
    )
    bars = _make_bars(
        [
            dict(trade_date="2024-01-02", symbol="A", open=10.0, high=10.5, low=10.0, close=10.5),  # 涨
            dict(trade_date="2024-01-02", symbol="B", open=10.0, high=10.2, low=10.0, close=10.1),  # 涨
            dict(trade_date="2024-01-02", symbol="C", open=10.0, high=10.0, low=9.5, close=9.5),    # 跌
            dict(trade_date="2024-01-02", symbol="D", open=10.0, high=10.0, low=10.0, close=10.0),  # 平
            dict(trade_date="2024-01-02", symbol="E", open=10.0, high=10.0, low=9.8, close=9.9),    # 跌
        ]
    )
    counts = limit_up_down_counts(bars, prev_close).loc["2024-01-02"]
    assert counts["advance"] == 2  # A, B
    assert counts["decline"] == 2  # C, E
    assert counts["limit_up_count"] == 0
    assert counts["limit_down_count"] == 0


# ---------------------------------------------------------------------------
# test_consecutive_board_height：S1 连续 3 日涨停 → 3；断板后归零
# ---------------------------------------------------------------------------
def test_consecutive_board_height() -> None:
    # S1：连续 3 日涨停（前收逐日更新为前日 close）
    prev_close_map = {
        "S1": {  # trade_date -> 前收
            "2024-01-02": 10.0,
            "2024-01-03": 11.0,
            "2024-01-04": 12.1,
            "2024-01-05": 13.0,  # 断板日：close 不达涨停
        },
        "S2": {  # 始终未涨停
            "2024-01-02": 10.0,
            "2024-01-03": 10.2,
            "2024-01-04": 10.1,
            "2024-01-05": 10.3,
        },
    }
    # 涨停价：01-02=11.00, 01-03=12.10, 01-04=13.31, 01-05=14.30
    bars = _make_bars(
        [
            dict(trade_date="2024-01-02", symbol="S1", open=10.5, high=11.00, low=10.4, close=11.00),
            dict(trade_date="2024-01-03", symbol="S1", open=11.5, high=12.10, low=11.4, close=12.10),
            dict(trade_date="2024-01-04", symbol="S1", open=12.5, high=13.31, low=12.4, close=13.31),
            dict(trade_date="2024-01-05", symbol="S1", open=13.5, high=13.50, low=13.0, close=13.00),  # 断板
            # S2 全程未涨停
            dict(trade_date="2024-01-02", symbol="S2", open=10.0, high=10.5, low=10.0, close=10.2),
            dict(trade_date="2024-01-03", symbol="S2", open=10.2, high=10.4, low=10.1, close=10.1),
            dict(trade_date="2024-01-04", symbol="S2", open=10.1, high=10.6, low=10.0, close=10.3),
            dict(trade_date="2024-01-05", symbol="S2", open=10.3, high=10.8, low=10.2, close=10.7),
        ]
    )
    height = consecutive_board_height(bars, prev_close_map)
    # 最新日（2024-01-05）S1 已断板 → 0；S2 始终 0
    assert int(height.loc["S1"]) == 0
    assert int(height.loc["S2"]) == 0

    # 截断到断板前（仅前 3 日）验证连板 = 3
    bars_pre = bars[bars["trade_date"] <= "2024-01-04"].copy()
    height_pre = consecutive_board_height(bars_pre, prev_close_map)
    assert int(height_pre.loc["S1"]) == 3
    assert int(height_pre.loc["S2"]) == 0


# ---------------------------------------------------------------------------
# test_seal_rate：触及涨停 5 家，收盘封 3 家 → 0.6
# ---------------------------------------------------------------------------
def test_seal_rate() -> None:
    prev_close = pd.Series({f"S{i}": 10.0 for i in range(5)}, name="prev_close")
    up = _limit_price(10.0)  # 11.00
    bars = _make_bars(
        [
            # 3 家收盘封板
            dict(trade_date="2024-01-02", symbol="S0", open=10.5, high=up, low=10.4, close=up),
            dict(trade_date="2024-01-02", symbol="S1", open=10.6, high=up, low=10.5, close=up),
            dict(trade_date="2024-01-02", symbol="S2", open=10.7, high=up, low=10.6, close=up),
            # 2 家触及涨停但收盘回落（炸板）
            dict(trade_date="2024-01-02", symbol="S3", open=10.5, high=up, low=10.3, close=10.5),
            dict(trade_date="2024-01-02", symbol="S4", open=10.5, high=up, low=10.2, close=10.4),
        ]
    )
    rate = seal_rate(bars, prev_close)
    assert rate == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# test_breadth_factor_series：per date (up-down)/total，时间序列长度=date 数
# ---------------------------------------------------------------------------
def test_breadth_factor_series() -> None:
    # 两日：d1 → (2-1)/3；d2 → (1-2)/3
    prev_close_series = pd.DataFrame(
        [
            dict(trade_date="2024-01-02", symbol="S1", prev_close=10.0),
            dict(trade_date="2024-01-02", symbol="S2", prev_close=10.0),
            dict(trade_date="2024-01-02", symbol="S3", prev_close=10.0),
            dict(trade_date="2024-01-03", symbol="S1", prev_close=11.0),
            dict(trade_date="2024-01-03", symbol="S2", prev_close=11.0),
            dict(trade_date="2024-01-03", symbol="S3", prev_close=11.0),
        ]
    )
    up1, down1 = _limit_price(10.0), _limit_down_price(10.0)
    up2, down2 = _limit_price(11.0), _limit_down_price(11.0)
    bars = _make_bars(
        [
            # d1: S1 涨停, S2 涨停, S3 跌停 → (2-1)/3
            dict(trade_date="2024-01-02", symbol="S1", open=10.5, high=up1, low=10.4, close=up1),
            dict(trade_date="2024-01-02", symbol="S2", open=10.5, high=up1, low=10.4, close=up1),
            dict(trade_date="2024-01-02", symbol="S3", open=9.5, high=9.5, low=down1, close=down1),
            # d2: S1 涨停, S2 跌停, S3 跌停 → (1-2)/3
            dict(trade_date="2024-01-03", symbol="S1", open=11.5, high=up2, low=11.4, close=up2),
            dict(trade_date="2024-01-03", symbol="S2", open=10.5, high=10.5, low=down2, close=down2),
            dict(trade_date="2024-01-03", symbol="S3", open=10.5, high=10.5, low=down2, close=down2),
        ]
    )
    series = breadth_factor_series(bars, prev_close_series)
    assert isinstance(series, pd.DataFrame)
    assert {"trade_date", "breadth_value"} == set(series.columns)
    assert len(series) == 2
    s = series.set_index("trade_date")["breadth_value"]
    assert s.loc["2024-01-02"] == pytest.approx((2 - 1) / 3)
    assert s.loc["2024-01-03"] == pytest.approx((1 - 2) / 3)


# ---------------------------------------------------------------------------
# test_no_limit_up_zero_division：无涨停日 seal_rate 不崩
# ---------------------------------------------------------------------------
def test_no_limit_up_zero_division() -> None:
    prev_close = pd.Series({"S1": 10.0, "S2": 10.0}, name="prev_close")
    bars = _make_bars(
        [
            dict(trade_date="2024-01-02", symbol="S1", open=10.0, high=10.5, low=10.0, close=10.5),
            dict(trade_date="2024-01-02", symbol="S2", open=10.0, high=10.2, low=10.0, close=10.1),
        ]
    )
    rate = seal_rate(bars, prev_close)
    # 无触及涨停 → 0（明确语义，非 nan）
    assert rate == pytest.approx(0.0)
