"""交易规则 golden cases（设计 v0.5 §4.1.6）。

设计意图：规则变更需人工 golden cases 标注——独立于规则表自验，
避免「用规则表自身生成的值校验规则表」的循环论证。本文件的所有
预期值均来自人工核验（对照各交易所规则文档与现行政策），作为
「输入 symbol + 决策时刻 → 预期命中规则事实」的固化契约。

字段约定：daily_limit_down 在 rule_json 中存「跌幅幅度的绝对值」
（如 0.10 表示 −10%），与 daily_limit_up 同号。golden case 断言
的是「人工核验后落库的真实值」，非规则表派生值。

当前范围（v0.5-scope）：只验证沪深主板股票 + 主板 ST。
科创/创业/北交/ETF/可转债作为后续扩展，不应命中当前默认规则。
"""
from __future__ import annotations

import datetime
import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.providers.rule_loader import load_rules
from quant.providers.trading_rule import TradingRuleProvider


@pytest.fixture
def store(tmp_db):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)  # 装入当前范围种子规则（3 条）
    yield s
    s.stop()


def _rule_json(store: SqliteStore, symbol: str, when: datetime.date) -> dict:
    """rules_for 命中后返回 rule_json 反序列化后的 dict。"""
    p = TradingRuleProvider(store)
    hit = p.rules_for(symbol, when, require_verified=False)
    assert hit is not None, f"{symbol} @ {when} 未命中任何规则"
    return json.loads(hit.rule_json)


# ============================================================
# Golden case 1：沪市主板（600519 贵州茅台）
# 人工核验：tick=0.01，涨/跌停 ±10%，T+1，最小买入 100 股。
# ============================================================
def test_golden_sse_main_stock(store):
    """600519 @2024-06-14 命中 sse_main_stock，关键字段人工核验值。"""
    rule = _rule_json(store, "600519", datetime.date(2024, 6, 14))

    assert rule["tick"] == 0.01
    assert rule["daily_limit_up"] == 0.10
    # daily_limit_down 存跌幅幅度的绝对值（0.10 表示 −10%）
    assert rule["daily_limit_down"] == 0.10
    assert rule["settlement_T"] == 1
    assert rule["min_buy"] == 100


def test_deferred_products_do_not_match_current_rules(store):
    """当前阶段外板块/品种不应命中当前默认规则。"""
    p = TradingRuleProvider(store)

    for symbol in ("688981", "300750", "830799", "510300", "113001"):
        assert p.rules_for(symbol, datetime.date(2024, 6, 14)) is None
