"""Instrument 模型测试：ST 时变状态（设计 v0.5 §4.1.3）。

ST 是时变状态（股票某段时期 ST/*ST/退市），用 StPeriod 时段建模；
Instrument.is_st(on) 判断 on 是否落入任一 ST 时段（右开区间）。
"""
from __future__ import annotations

from datetime import date

from quant.data.instrument import Instrument, StPeriod


def test_st_period_active():
    """end=None 表示至今仍 ST，任意未来日均命中。"""
    inst = Instrument(
        symbol="600519",
        market="SSE",
        board="main",
        product_type="stock",
        st_periods=[StPeriod(symbol="600519", start=date(2024, 1, 1), end=None)],
    )
    assert inst.is_st(date(2024, 6, 1)) is True
    assert inst.is_st(date(2099, 12, 31)) is True


def test_st_period_window():
    """闭区间右开：start<=on<end 命中；on>=end 或 on<start 不命中。"""
    inst = Instrument(
        symbol="600519",
        market="SSE",
        board="main",
        product_type="stock",
        st_periods=[
            StPeriod(
                symbol="600519",
                start=date(2024, 1, 1),
                end=date(2024, 6, 1),
            )
        ],
    )
    # 区间内
    assert inst.is_st(date(2024, 1, 1)) is True
    assert inst.is_st(date(2024, 5, 31)) is True
    # 右端点不命中（右开）
    assert inst.is_st(date(2024, 6, 1)) is False
    # 左端点之前不命中
    assert inst.is_st(date(2023, 12, 31)) is False


def test_instrument_multiple_periods():
    """多时段：任一命中即视为 ST。"""
    inst = Instrument(
        symbol="000001",
        market="SZSE",
        board="main",
        product_type="stock",
        st_periods=[
            StPeriod(
                symbol="000001",
                start=date(2020, 1, 1),
                end=date(2020, 6, 1),
                kind="ST",
            ),
            StPeriod(
                symbol="000001",
                start=date(2023, 3, 1),
                end=date(2023, 9, 1),
                kind="*ST",
            ),
        ],
    )
    assert inst.is_st(date(2020, 3, 1)) is True
    assert inst.is_st(date(2023, 5, 1)) is True
    # 两个时段之间空档期不命中
    assert inst.is_st(date(2021, 1, 1)) is False
    assert inst.is_st(date(2024, 1, 1)) is False


def test_instrument_not_st():
    """无 st_periods → 任何日期均不视为 ST。"""
    inst = Instrument(
        symbol="600519",
        market="SSE",
        board="main",
        product_type="stock",
    )
    assert inst.st_periods == []
    assert inst.is_st(date(2024, 1, 1)) is False
