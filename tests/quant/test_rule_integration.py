"""交易规则集成测试：load → query → 校验 全链路串联（设计 v0.5 §6/§11）。

区别于 test_rule_loader（单测装载）与 test_trading_rule_golden（golden case 事实），
本文件验证三者协同：
- load_rules 写入后 rules_for 多 symbol 多日期命中正确（复用 golden 事实）
- check_no_overlap 全表空（种子区间互斥）
- require_verified 实盘阻断语义：费用 provisional 阻断实盘返回 None
- rules_for 返回真实 TradingRule 而非 None（M0 空表已升级为真数据）
"""
from __future__ import annotations

import datetime
import json

import pytest

from quant.data.models import TradingRule
from quant.data.sqlite_store import SqliteStore
from quant.providers.rule_loader import load_rules
from quant.providers.trading_rule import TradingRuleProvider


@pytest.fixture
def store(tmp_db):
    """起停一个 SqliteStore 并装入种子规则，确保用例结束线程被回收。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)
    yield s
    s.stop()


def test_full_pipeline(store):
    """全链路：load → 多 symbol 多日期命中正确 → 全表 check_no_overlap 空。

    复用 golden case 中人工核验的事实（涨跌停幅度的路由命中），
    作为集成链路的端到端契约。
    """
    p = TradingRuleProvider(store)

    # 沪市主板 600519：±10%
    sse_main = p.rules_for("600519", datetime.date(2024, 6, 14))
    assert sse_main is not None
    assert json.loads(sse_main.rule_json)["daily_limit_up"] == 0.10

    # 当前阶段外品种不命中默认交易规则；扩展前须补 source/fixture。
    assert p.rules_for("688981", datetime.date(2024, 6, 14)) is None
    assert p.rules_for("300750", datetime.date(2020, 1, 6)) is None
    assert p.rules_for("830799", datetime.date(2024, 6, 14)) is None
    assert p.rules_for("510300", datetime.date(2024, 6, 14)) is None
    assert p.rules_for("113001", datetime.date(2024, 6, 14)) is None

    # 全表区间不重叠（当前种子仅沪深主板股票 + ST 主板）
    rows = store.query_all(
        "SELECT rule_id, market, board, product_type, "
        "effective_from, effective_to FROM trading_rule"
    )
    assert p.check_no_overlap(rows) == []


def test_require_verified_blocks_due_to_provisional_fees(store):
    """种子规则结构 verified 但费用明细 provisional（§11）。

    实盘路径（require_verified=True）应被阻断返回 None；
    回测/展示路径（require_verified=False）命中返回规则。
    """
    p = TradingRuleProvider(store)
    t = datetime.date(2024, 6, 14)

    # 实盘：费用 provisional 阻断
    assert p.rules_for("600519", t, require_verified=True) is None

    # 回测/展示：不阻断，命中返回
    hit = p.rules_for("600519", t, require_verified=False)
    assert hit is not None
    assert hit.rule_id == "sse_main_stock"


def test_rules_return_real_data_not_none(store):
    """rules_for 返回真实 TradingRule 而非 None（M0 空表已升级为真数据）。

    断言返回类型与关键字段齐全，证明装载链路产出可消费的规则对象。
    """
    p = TradingRuleProvider(store)
    hit = p.rules_for("600519", datetime.date(2024, 6, 14))

    assert isinstance(hit, TradingRule)
    assert hit is not None
    # 关键字段齐全且非空
    assert hit.rule_id == "sse_main_stock"
    assert hit.market == "SSE"
    assert hit.board == "main"
    assert hit.product_type == "stock"
    assert hit.source_confidence == "verified"
    assert hit.rule_json  # JSON 字符串非空
    # rule_json 可正常反序列化为含交易事实的 dict
    payload = json.loads(hit.rule_json)
    assert "daily_limit_up" in payload
    assert "fees" in payload
