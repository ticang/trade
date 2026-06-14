"""TradingRule 种子装载测试（设计 v0.5 §6 trading_rule 录入路径）。

覆盖 load_rules：
- 读 rules_v1.yaml → 写 trading_rule 表，字段对齐
- rule_json 列存 JSON 字符串（YAML dict 经 json.dumps）
- effective_to=null → SQL NULL；日期串原样存
- 装载后 check_no_overlap 返回空（种子区间不重叠，ETF 两 board 已区分）
- 幂等：连续 load 不翻倍
- strict_overlap=True：写入后检测到区间冲突 → 抛 ValueError
"""
from __future__ import annotations

import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.providers.rule_loader import DEFAULT_RULES_YAML, load_rules
from quant.providers.trading_rule import TradingRuleProvider


@pytest.fixture
def store(tmp_db):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    yield s
    s.stop()


def _count(store: SqliteStore) -> int:
    """读 trading_rule 行数。"""
    rows = store.query_all("SELECT COUNT(*) AS n FROM trading_rule")
    return int(rows[0]["n"])


def test_load_rules_populates_table(store):
    """load_rules → trading_rule 表 10 行；抽 sse_main_stock 字段对。"""
    n = load_rules(store)
    assert n == 10
    assert _count(store) == 10

    rows = store.query_all(
        "SELECT rule_id, market, board, product_type, "
        "effective_from, effective_to, source_url, source_confidence, rule_json "
        "FROM trading_rule WHERE rule_id = ?",
        ("sse_main_stock",),
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["market"] == "SSE"
    assert r["board"] == "main"
    assert r["product_type"] == "stock"
    assert r["effective_from"] == "2020-01-01"
    assert r["effective_to"] is None  # null → SQL NULL
    assert r["source_confidence"] == "verified"
    rule = json.loads(r["rule_json"])
    assert rule["daily_limit_up"] == 0.10


def test_rule_json_serialized(store):
    """rule_json 列存 JSON 字符串，json.loads 还原 dict 含 tick/daily_limit_up/fees。"""
    load_rules(store)
    rows = store.query_all(
        "SELECT rule_json FROM trading_rule WHERE rule_id = ?",
        ("sse_star_stock",),
    )
    raw = rows[0]["rule_json"]
    assert isinstance(raw, str)  # 列存字符串非 BLOB
    rule = json.loads(raw)
    assert rule["tick"] == 0.01
    assert rule["daily_limit_up"] == 0.20
    assert rule["settlement_T"] == 1
    # 费率嵌套结构保留
    assert "fees" in rule
    assert rule["fees"]["stamp"]["value"] == 0.0005
    assert rule["fees"]["commission"]["value"] is None


def test_effective_to_null_handled(store):
    """effective_to=null → SQL NULL；pre_reform 那条 effective_to='2020-08-23' 原样存。"""
    load_rules(store)

    null_rows = store.query_all(
        "SELECT effective_to FROM trading_rule WHERE rule_id = ?",
        ("sse_main_stock",),
    )
    assert null_rows[0]["effective_to"] is None

    pre_rows = store.query_all(
        "SELECT effective_to FROM trading_rule WHERE rule_id = ?",
        ("szse_chinext_stock_pre_reform",),
    )
    assert pre_rows[0]["effective_to"] == "2020-08-23"


def test_no_overlap_after_load(store):
    """种子装载后 check_no_overlap(全部行) 返回空（含 ETF 两 board 已区分）。"""
    load_rules(store)
    rows = store.query_all(
        "SELECT rule_id, market, board, product_type, "
        "effective_from, effective_to FROM trading_rule"
    )
    p = TradingRuleProvider(store)
    assert p.check_no_overlap(rows) == []


def test_load_is_idempotent(store):
    """连续 load 两次，行数仍 10（INSERT OR REPLACE by rule_id）。"""
    load_rules(store)
    load_rules(store)
    assert _count(store) == 10


def test_strict_overlap_detects_conflict(store):
    """strict_overlap=True：预先插一条与 sse_main_stock 重叠的规则，
    再次 load 应抛 ValueError（重叠保护）。"""
    load_rules(store)
    assert store.flush(timeout=5.0)

    # 手动插一条与 sse_main_stock 区间重叠的同行（rule_id 不同，区间相交）
    store.execute(
        "INSERT INTO trading_rule (rule_id, market, board, product_type, "
        "effective_from, effective_to, source_url, source_confidence, rule_json, "
        "reviewed_by, reviewed_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "sse_main_dup",
            "SSE",
            "main",
            "stock",
            "2020-01-01",
            None,  # 与 sse_main_stock 区间相交（均无限期）
            "http://example/",
            "verified",
            "{}",
            None,
            None,
        ),
    )
    assert store.flush(timeout=5.0)

    # 再 load：种子写入后全表校验发现重叠 → ValueError
    with pytest.raises(ValueError):
        load_rules(store, strict_overlap=True)


def test_default_rules_yaml_points_to_seed():
    """DEFAULT_RULES_YAML 指向 data/rules_v1.yaml 且文件存在。"""
    assert DEFAULT_RULES_YAML.name == "rules_v1.yaml"
    assert DEFAULT_RULES_YAML.exists()
