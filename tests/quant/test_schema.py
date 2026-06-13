"""DDL 幂等性与表存在性测试。

覆盖设计 v0.5 §6 的 SQLite 事务库与 DuckDB 数据库表定义。
"""
import sqlite3

import duckdb
import pytest

from quant.data import schema


# SQLite 关键表（事务库）
SQLITE_EXPECTED = {
    "account",
    "orders",
    "order_event",
    "fills",
    "position",
    "audit_event",
    "actor_trade",
    "experiment",
    "agent_run",
    "job_run",
    "trading_rule",
    "strategy_lifecycle",
    "source_audit",
}

# DuckDB 关键表（数据库）
DUCKDB_EXPECTED = {
    "instrument",
    "bar",
    "factor_value",
    "tick",
    "pit_field",
    "factor_snapshot",
    "data_snapshot",
}


def _sqlite_table_names(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def _duckdb_table_names(conn) -> set[str]:
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    )
    return {row[0] for row in cur.fetchall()}


def test_create_sqlite_creates_all_tables():
    """create_sqlite 应建立全部事务库表。"""
    conn = sqlite3.connect(":memory:")
    try:
        schema.create_sqlite(conn)
        names = _sqlite_table_names(conn)
    finally:
        conn.close()

    missing = SQLITE_EXPECTED - names
    assert not missing, f"SQLite 缺表: {missing}"


def test_create_duckdb_creates_all_tables():
    """create_duckdb 应建立全部数据库表。"""
    conn = duckdb.connect(":memory:")
    try:
        schema.create_duckdb(conn)
        names = _duckdb_table_names(conn)
    finally:
        conn.close()

    missing = DUCKDB_EXPECTED - names
    assert not missing, f"DuckDB 缺表: {missing}"


def test_create_sqlite_is_idempotent():
    """重复执行 create_sqlite 不应报错（IF NOT EXISTS）。"""
    conn = sqlite3.connect(":memory:")
    try:
        schema.create_sqlite(conn)
        schema.create_sqlite(conn)  # 第二次应幂等
        names = _sqlite_table_names(conn)
    finally:
        conn.close()

    assert "orders" in names


def test_create_duckdb_is_idempotent():
    """重复执行 create_duckdb 不应报错（IF NOT EXISTS）。"""
    conn = duckdb.connect(":memory:")
    try:
        schema.create_duckdb(conn)
        schema.create_duckdb(conn)
        names = _duckdb_table_names(conn)
    finally:
        conn.close()

    assert "bar" in names


def test_sqlite_ddl_string_not_empty():
    """SQLITE_DDL 常量应为非空字符串。"""
    assert isinstance(schema.SQLITE_DDL, str)
    assert "CREATE TABLE" in schema.SQLITE_DDL


def test_duckdb_ddl_string_not_empty():
    """DUCKDB_DDL 常量应为非空字符串。"""
    assert isinstance(schema.DUCKDB_DDL, str)
    assert "CREATE TABLE" in schema.DUCKDB_DDL


def test_models_importable():
    """dataclass 模型应可导入且字段齐全。"""
    from quant.data import models

    # 关键 dataclass 必须存在
    for cls_name in (
        "Instrument",
        "Bar",
        "PointInTime",
        "TradingRule",
        "Account",
    ):
        assert hasattr(models, cls_name), f"models 缺 dataclass: {cls_name}"


def test_sqlite_key_columns_present():
    """orders 表关键列与唯一约束应在 DDL 中（设计 v0.5 §6）。"""
    assert "client_order_id" in schema.SQLITE_DDL
    assert "UNIQUE(account_id, client_order_id)" in schema.SQLITE_DDL
    assert "stop_loss" in schema.SQLITE_DDL


def test_duckdb_key_columns_present():
    """bar 表 PIT 相关列应在 DDL 中（设计 v0.5 §6）。"""
    assert "pit_confidence" in schema.DUCKDB_DDL
    assert "available_at" in schema.DUCKDB_DDL
    assert "snapshot_id" in schema.DUCKDB_DDL
