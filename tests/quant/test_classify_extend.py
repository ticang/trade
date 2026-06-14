"""classify 扩展测试：可转债前缀 + 经 instrument 精分类（设计 v0.5 §4.1.3）。

- 可转债有独立代码段（11x/113x/123x），classify_symbol 直接识别。
- classify_with_instrument：当 instrument 提供且 symbol 命中时，
  以 instrument.market/board/product_type 为准，并在 ST 时段/跨境 ETF 时改写 board。
"""
from __future__ import annotations

from datetime import date

from quant.data.instrument import Instrument, StPeriod
from quant.providers.trading_rule import (
    classify_symbol,
    classify_with_instrument,
)


def test_classify_convertible_bond_codes():
    """可转债独立代码段 → (BOND, bond, bond)。"""
    assert classify_symbol("113001") == ("BOND", "bond", "bond")
    assert classify_symbol("110001") == ("BOND", "bond", "bond")
    assert classify_symbol("123001") == ("BOND", "bond", "bond")


def test_classify_existing_prefixes_unchanged():
    """既有前缀规则保持向后兼容（股票/基金/北交所不变）。"""
    assert classify_symbol("600519") == ("SSE", "main", "stock")
    assert classify_symbol("688981") == ("SSE", "star", "stock")
    assert classify_symbol("000001") == ("SZSE", "main", "stock")
    assert classify_symbol("300750") == ("SZSE", "chinext", "stock")
    assert classify_symbol("830799") == ("BSE", "main", "stock")
    assert classify_symbol("510300") == ("ETF", "etp", "fund")


def test_classify_with_instrument_st():
    """instrument 命中 + 该时刻 ST → board 改 'st'（命中 st_main 规则）。"""
    on = date(2024, 6, 1)
    inst = Instrument(
        symbol="600519",
        market="SSE",
        board="main",
        product_type="stock",
        st_periods=[StPeriod(symbol="600519", start=date(2024, 1, 1), end=None)],
    )
    instruments = {"600519": inst}
    market, board, product_type = classify_with_instrument("600519", on, instruments)
    assert market == "SSE"
    assert board == "st"
    assert product_type == "stock"


def test_classify_with_instrument_fallback():
    """无 instrument（None 或 symbol 未命中）→ 回退 classify_symbol。"""
    on = date(2024, 6, 1)
    # instrument=None
    assert classify_with_instrument("600519", on, None) == (
        "SSE",
        "main",
        "stock",
    )
    # symbol 未在 instrument 字典中
    assert classify_with_instrument("688981", on, {"600519": Instrument(
        symbol="600519", market="SSE", board="main", product_type="stock"
    )}) == ("SSE", "star", "stock")


def test_classify_with_instrument_etf_crossborder():
    """跨境 ETF（etf_crossborder=True）→ board='etp_crossborder'。"""
    on = date(2024, 6, 1)
    inst = Instrument(
        symbol="513100",
        market="ETF",
        board="etp",
        product_type="fund",
        etf_crossborder=True,
    )
    instruments = {"513100": inst}
    market, board, product_type = classify_with_instrument("513100", on, instruments)
    assert market == "ETF"
    assert board == "etp_crossborder"
    assert product_type == "fund"
