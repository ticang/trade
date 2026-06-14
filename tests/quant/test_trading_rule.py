"""TradingRuleProvider 区间查询测试（设计 v0.5 §4.1.3/§6）。

覆盖：
- classify_symbol：A 股 symbol→(market,board,product_type) 简化映射
- rules_for：按 effective_from <= t < effective_to 命中区间，反序列化 rule_json
- check_no_overlap：同 (market,board,product_type) 区间不重叠校验（M0 预留，M0.5 录入用）
"""
from __future__ import annotations

import datetime

import pytest

from quant.data.models import TradingRule
from quant.data.sqlite_store import SqliteStore
from quant.providers.trading_rule import TradingRuleProvider, classify_symbol


@pytest.fixture
def store(tmp_db):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    yield s
    s.stop()


# trading_rule 插入语句（列对齐 schema.SQLITE_DDL）
_INSERT_RULE = (
    "INSERT INTO trading_rule (rule_id, market, board, product_type, "
    "effective_from, effective_to, source_url, source_confidence, rule_json, "
    "reviewed_by, reviewed_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _insert(
    store: SqliteStore,
    rule_id: str,
    market: str,
    board: str,
    product_type: str,
    effective_from: datetime.date,
    effective_to: datetime.date | None,
) -> None:
    """插一条规则并 flush 落盘。"""
    store.execute(
        _INSERT_RULE,
        (
            rule_id,
            market,
            board,
            product_type,
            effective_from.isoformat(),
            effective_to.isoformat() if effective_to else None,
            "http://example/rule",
            "official",
            '{"price_tick": 0.01}',
            None,
            None,
        ),
    )
    assert store.flush(timeout=5.0)


def test_classify_symbol():
    """A 股 symbol 前缀→(market,board,product_type) 简化映射。"""
    assert classify_symbol("600519") == ("SSE", "main", "stock")
    assert classify_symbol("688981") == ("SSE", "star", "stock")
    assert classify_symbol("000001") == ("SZSE", "main", "stock")
    assert classify_symbol("300750") == ("SZSE", "chinext", "stock")


def test_empty_table_returns_none(store):
    """空表查询应返回 None。"""
    p = TradingRuleProvider(store)
    assert p.rules_for("600519", datetime.date(2024, 3, 15)) is None


def test_rule_hits_correct_interval(store):
    """两条同 (SSE,main,stock) 规则区间相邻不重叠：
    查 2024-03-15 命中第二条（2024 起），查 2022-06-01 命中第一条（2020-2023）。
    """
    _insert(
        store,
        "R-OLD",
        "SSE",
        "main",
        "stock",
        datetime.date(2020, 1, 1),
        datetime.date(2023, 12, 31),
    )
    _insert(
        store,
        "R-NEW",
        "SSE",
        "main",
        "stock",
        datetime.date(2024, 1, 1),
        datetime.date(9999, 12, 31),
    )

    p = TradingRuleProvider(store)

    hit_new = p.rules_for("600519", datetime.date(2024, 3, 15))
    assert hit_new is not None
    assert isinstance(hit_new, TradingRule)
    assert hit_new.rule_id == "R-NEW"

    hit_old = p.rules_for("600519", datetime.date(2022, 6, 1))
    assert hit_old is not None
    assert hit_old.rule_id == "R-OLD"


def test_rule_outside_interval_returns_none(store):
    """仅有一条 2020-2023 规则，查 2024 应返回 None（区间右开）。"""
    _insert(
        store,
        "R-ONLY",
        "SSE",
        "main",
        "stock",
        datetime.date(2020, 1, 1),
        datetime.date(2023, 12, 31),
    )

    p = TradingRuleProvider(store)
    assert p.rules_for("600519", datetime.date(2024, 1, 1)) is None


def test_datetime_decision_time_accepted(store):
    """decision_time 传 datetime 应按其 date 部分查询。"""
    _insert(
        store,
        "R-DT",
        "SSE",
        "main",
        "stock",
        datetime.date(2020, 1, 1),
        datetime.date(9999, 12, 31),
    )

    p = TradingRuleProvider(store)
    hit = p.rules_for(
        "600519", datetime.datetime(2024, 6, 14, 9, 30, 0)
    )
    assert hit is not None
    assert hit.rule_id == "R-DT"


def test_check_no_overlap_detects_conflict(store):
    """check_no_overlap：相交区间→非空冲突列表；不交→空。

    M0 预留，M0.5 录入 trading_rule 前调用以校验区间不重叠。
    """
    # 先查全部规则行作为入参（模拟录入前已有数据）
    _insert(
        store,
        "R-A",
        "SSE",
        "main",
        "stock",
        datetime.date(2020, 1, 1),
        datetime.date(2024, 12, 31),
    )
    _insert(
        store,
        "R-B",
        "SSE",
        "main",
        "stock",
        datetime.date(2024, 1, 1),
        datetime.date(9999, 12, 31),
    )
    assert store.flush(timeout=5.0)

    p = TradingRuleProvider(store)
    rows = store.query_all(
        "SELECT rule_id, market, board, product_type, "
        "effective_from, effective_to FROM trading_rule"
    )
    conflicts = p.check_no_overlap(rows)
    assert conflicts, "相交区间应被检出冲突"

    # 不相交的两组：清空后重建
    for rid in ("R-A", "R-B"):
        store.execute("DELETE FROM trading_rule WHERE rule_id = ?", (rid,))
    assert store.flush(timeout=5.0)
    _insert(
        store,
        "R-C",
        "SSE",
        "main",
        "stock",
        datetime.date(2020, 1, 1),
        datetime.date(2023, 12, 31),
    )
    _insert(
        store,
        "R-D",
        "SSE",
        "main",
        "stock",
        datetime.date(2024, 1, 1),
        datetime.date(9999, 12, 31),
    )
    rows2 = store.query_all(
        "SELECT rule_id, market, board, product_type, "
        "effective_from, effective_to FROM trading_rule"
    )
    assert p.check_no_overlap(rows2) == []
