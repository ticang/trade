"""Instrument 路由集成验收（设计 v0.5 §4.1.3 / §6 / §11）。

load_rules(M0.5 种子) + InstrumentProvider 联动，端到端验证四类路由：
- ST 股（SZSE/st/stock，±5%）经 instrument ST 时变标记命中 st_main
- 可转债（BOND/bond/bond，±20%/T+0/tick0.001）命中 convertible_bond
- 跨境 ETF（ETF/etp_crossborder/fund，T+0）命中 etf_crossborder
- 普通股（SSE/main/stock，±10%）仍走主板规则

区别于 test_rules_with_instrument（rules_for 接 provider 单测）：
本文件侧重规则与 instrument 数据的协同路由终态，作为 §4.1.3 instrument 路由的验收门禁。
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
    """起停 SqliteStore 并装入种子规则。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)
    yield s
    s.stop()


def test_st_stock_routes_to_st_main(store):
    """ST 股（SZSE 主板 + ST 标记）经 instrument 命中 st_main（±5%）。

    st_main 规则三元组 (SZSE, st, stock)；instrument 标 ST 后 board 改 st，
    market 保留 SZSE，三元组命中 st_main。
    """
    t = datetime.date(2024, 6, 1)
    inst = Instrument(
        symbol="000001",
        market="SZSE",
        board="main",
        product_type="stock",
        st_periods=[
            StPeriod(symbol="000001", start=datetime.date(2020, 1, 1), end=None),
        ],
    )
    provider = InstrumentProvider(instruments={"000001": inst})
    p = TradingRuleProvider(store)

    hit = p.rules_for("000001", t, instrument_provider=provider)
    assert hit is not None
    assert hit.rule_id == "st_main"
    assert hit.market == "SZSE"
    assert hit.board == "st"
    payload = json.loads(hit.rule_json)
    assert payload["daily_limit_up"] == 0.05
    assert payload["daily_limit_down"] == 0.05


def test_convertible_bond_routes_to_convertible_bond(store):
    """可转债经 instrument 命中 convertible_bond（±20%/T+0/tick0.001）。"""
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
    assert payload["daily_limit_down"] == 0.20
    assert payload["settlement_T"] == 0
    assert payload["tick"] == 0.001


def test_etf_crossborder_routes_to_crossborder_rule(store):
    """跨境 ETF（etf_crossborder=True）经 instrument 命中 etf_crossborder（T+0）。"""
    t = datetime.date(2024, 6, 1)
    inst = Instrument(
        symbol="510900",
        market="ETF",
        board="etp",
        product_type="fund",
        etf_crossborder=True,
    )
    provider = InstrumentProvider(instruments={"510900": inst})
    p = TradingRuleProvider(store)

    hit = p.rules_for("510900", t, instrument_provider=provider)
    assert hit is not None
    assert hit.rule_id == "etf_crossborder"
    assert hit.board == "etp_crossborder"
    payload = json.loads(hit.rule_json)
    assert payload["settlement_T"] == 0


def test_normal_stock_still_main_board(store):
    """普通股（无 instrument_provider）仍走主板规则（±10%）。"""
    p = TradingRuleProvider(store)
    hit = p.rules_for("600519", datetime.date(2024, 6, 1))
    assert hit is not None
    assert hit.rule_id == "sse_main_stock"
    payload = json.loads(hit.rule_json)
    assert payload["daily_limit_up"] == 0.10


def test_seed_provider_classifies_st_and_crossborder():
    """InstrumentProvider.from_seed 加载 seed 后 classify 路由正确：
    - 600000 ST 时段内 → board='st'
    - 510900 → board='etp_crossborder'
    - 113001 → (BOND,bond,bond)
    """
    provider = InstrumentProvider.from_seed()

    # 600000 ST 时段内（seed 录 2020-2022）→ ST
    m, b, pt = provider.classify("600000", datetime.date(2021, 6, 1))
    assert (m, b, pt) == ("SSE", "st", "stock")

    # 600000 ST 时段外 → 回主板
    m2, b2, _ = provider.classify("600000", datetime.date(2024, 6, 1))
    assert (m2, b2) == ("SSE", "main")

    # 跨境 ETF
    m3, b3, pt3 = provider.classify("510900", datetime.date(2024, 6, 1))
    assert (m3, b3, pt3) == ("ETF", "etp_crossborder", "fund")

    # 可转债
    m4, b4, pt4 = provider.classify("113001", datetime.date(2024, 6, 1))
    assert (m4, b4, pt4) == ("BOND", "bond", "bond")
