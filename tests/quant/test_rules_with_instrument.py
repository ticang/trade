"""rules_for 接 instrument_provider 测试（设计 v0.5 §4.1.3）。

向后兼容：传 instrument_provider 时经其精分类（ST/可转债/跨境命中对应规则）；
不传则走旧 classify_symbol。本文件验证两条路径并存不互扰。
"""
from __future__ import annotations

import datetime
import json

import pytest

from quant.data.instrument import Instrument, StPeriod
from quant.data.instrument_provider import InstrumentProvider
from quant.data.sqlite_store import SqliteStore
from quant.providers.rule_loader import load_rules
from quant.providers.trading_rule import TradingRuleProvider


@pytest.fixture
def store(tmp_db):
    """起停 SqliteStore 并装入种子规则（含 st_main/convertible_bond/etf_crossborder）。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)
    yield s
    s.stop()


def _provider_with_st(symbol: str, market: str, on_st: bool) -> InstrumentProvider:
    """构造含一张 ST 股（指定市场）的 InstrumentProvider。

    on_st=True：ST 时段覆盖 2020-至今，任意时刻均判 ST；
    on_st=False：无 ST 时段。
    """
    periods = (
        [StPeriod(symbol=symbol, start=datetime.date(2020, 1, 1), end=None)]
        if on_st else []
    )
    inst = Instrument(
        symbol=symbol,
        market=market,
        board="main",
        product_type="stock",
        st_periods=periods,
    )
    return InstrumentProvider(instruments={symbol: inst})


def test_rules_for_st_routes_to_st_main(store):
    """传 instrument_provider（含 ST）→ rules_for 命中 st_main（±5%）。

    st_main 规则 (SZSE, st, stock)，故用 SZSE 主板 symbol + ST 标记。
    """
    t = datetime.date(2024, 6, 1)
    provider = _provider_with_st("000001", "SZSE", on_st=True)
    p = TradingRuleProvider(store)

    hit = p.rules_for("000001", t, instrument_provider=provider)
    assert hit is not None
    assert hit.rule_id == "st_main"
    payload = json.loads(hit.rule_json)
    assert payload["daily_limit_up"] == 0.05
    assert payload["daily_limit_down"] == 0.05


def test_rules_for_convertible_bond_via_provider(store):
    """传 instrument_provider（含可转债）→ rules_for 命中 convertible_bond（±20%/T+0）。"""
    t = datetime.date(2024, 6, 1)
    inst = Instrument(
        symbol="113001", market="BOND", board="bond", product_type="bond"
    )
    provider = InstrumentProvider(instruments={"113001": inst})
    p = TradingRuleProvider(store)

    hit = p.rules_for("113001", t, instrument_provider=provider)
    assert hit is not None
    assert hit.rule_id == "convertible_bond"
    payload = json.loads(hit.rule_json)
    assert payload["daily_limit_up"] == 0.20
    assert payload["settlement_T"] == 0
    assert payload["tick"] == 0.001


def test_rules_for_backwards_compatible_without_provider(store):
    """无 instrument_provider → 走旧 classify_symbol（向后兼容，既有调用不破）。

    600519 普通沪市主板 → sse_main_stock（±10%）。
    """
    p = TradingRuleProvider(store)
    hit = p.rules_for("600519", datetime.date(2024, 6, 1))
    assert hit is not None
    assert hit.rule_id == "sse_main_stock"
    payload = json.loads(hit.rule_json)
    assert payload["daily_limit_up"] == 0.10


def test_rules_for_st_false_when_period_outside(store):
    """instrument_provider 命中但 on 不在 ST 时段 → 走主板规则（非 st_main）。

    ST 时段 2020-2022，查 2024（时段外）→ is_st False → 回主板路由。
    """
    inst = Instrument(
        symbol="000001",
        market="SZSE",
        board="main",
        product_type="stock",
        st_periods=[
            StPeriod(symbol="000001", start=datetime.date(2020, 1, 1),
                     end=datetime.date(2022, 12, 31)),
        ],
    )
    provider = InstrumentProvider(instruments={"000001": inst})
    p = TradingRuleProvider(store)

    # 时段外 → 主板
    hit_outside = p.rules_for(
        "000001", datetime.date(2024, 6, 1), instrument_provider=provider
    )
    assert hit_outside is not None
    assert hit_outside.rule_id == "szse_main_stock"

    # 时段内 → ST
    hit_inside = p.rules_for(
        "000001", datetime.date(2021, 6, 1), instrument_provider=provider
    )
    assert hit_inside is not None
    assert hit_inside.rule_id == "st_main"
