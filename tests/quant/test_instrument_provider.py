"""InstrumentProvider + seed 测试（设计 v0.5 §4.1.3 instrument 路由）。

覆盖：
- from_seed：读 instrument_seed.yaml 构造 Instrument dict
- is_st：经 instrument 时变判定，未命中 symbol 返回 False
- classify：经 instrument 精分类（ST→board st；跨境→etp_crossborder）；未命中回退 classify_symbol
"""
from __future__ import annotations

from datetime import date

from quant.data.instrument_provider import InstrumentProvider


def test_from_seed_loads_known_samples():
    """from_seed 默认读 quant/data/instrument_seed.yaml，加载已知样本。"""
    provider = InstrumentProvider.from_seed()
    # 600519 沪市主板，无 ST
    inst = provider.get("600519")
    assert inst is not None
    assert inst.market == "SSE"
    assert inst.board == "main"
    assert inst.product_type == "stock"
    assert inst.st_periods == []

    # 600000 沪市主板，含一段 st_periods
    inst_600000 = provider.get("600000")
    assert inst_600000 is not None
    assert inst_600000.market == "SSE"
    assert inst_600000.board == "main"
    assert len(inst_600000.st_periods) >= 1


def test_is_st_time_varying():
    """is_st 时变：ST 时段内 True，时段外 False；未命中 symbol 返回 False。"""
    provider = InstrumentProvider.from_seed()
    inst = provider.get("600000")
    assert inst is not None
    period = inst.st_periods[0]

    # 时段内（start<=on<end）→ True
    on_in = period.start
    assert provider.is_st("600000", on_in) is True

    # 时段外（end 当日视为已退出，右开）→ False
    if period.end is not None:
        assert provider.is_st("600000", period.end) is False

    # 未命中 symbol → False
    assert provider.is_st("99999999", date(2024, 6, 1)) is False


def test_classify_st_routes_to_st_board():
    """classify：instrument 命中且 ST → board='st'。"""
    provider = InstrumentProvider.from_seed()
    inst = provider.get("600000")
    period = inst.st_periods[0]
    market, board, product_type = provider.classify("600000", period.start)
    assert market == "SSE"
    assert board == "st"
    assert product_type == "stock"


def test_classify_convertible_bond():
    """classify：可转债 instrument 命中 → (BOND,bond,bond)。"""
    provider = InstrumentProvider.from_seed()
    market, board, product_type = provider.classify("113001", date(2024, 6, 1))
    assert (market, board, product_type) == ("BOND", "bond", "bond")


def test_classify_etf_crossborder():
    """classify：跨境 ETF（etf_crossborder=True）→ board='etp_crossborder'。"""
    provider = InstrumentProvider.from_seed()
    market, board, product_type = provider.classify("510900", date(2024, 6, 1))
    assert market == "ETF"
    assert board == "etp_crossborder"
    assert product_type == "fund"


def test_classify_falls_back_when_symbol_missing():
    """classify：symbol 未在 instrument 中 → 回退 classify_symbol。"""
    provider = InstrumentProvider.from_seed()
    # 688981 不在 seed，且科创板为延期范围 → unsupported
    market, board, product_type = provider.classify("688981", date(2024, 6, 1))
    assert (market, board, product_type) == (
        "UNSUPPORTED",
        "unsupported",
        "unsupported",
    )
