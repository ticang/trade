"""Schema DDL：SQLite 事务库 + DuckDB 数据库。

表定义直接取自设计 v0.5 §6，列名与类型精确照抄，勿臆造。
- SQLite：account/orders/order_event/fills/position/audit_event/actor_trade/
  experiment/agent_run/job_run/trading_rule/strategy_lifecycle/source_audit
- DuckDB：instrument/bar/factor_value/tick/pit_field/factor_snapshot/data_snapshot

注：设计原文中 trading_rule 含 `CHECK (no_overlap_per_product)` 区间不重叠约束，
SQLite/DuckDB 均不支持该表达式形式，故 DDL 不加该 CHECK，改由应用层在 M0.5 校验
（写入 trading_rule 前检查 effective 区间不重叠）。
"""
from __future__ import annotations

import sqlite3
from typing import Iterable


# 设计 v0.5 §6 —— SQLite 事务库
SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS account (account_id TEXT PRIMARY KEY, broker TEXT, env TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS orders (order_id TEXT PRIMARY KEY, account_id TEXT, strategy TEXT, symbol TEXT, side TEXT,
    qty REAL, price REAL, status TEXT, broker TEXT, client_order_id TEXT, rule_version TEXT,
    stop_loss REAL, take_profit REAL, created_ts INTEGER, updated_ts INTEGER, reason TEXT,
    UNIQUE(account_id, client_order_id));
CREATE TABLE IF NOT EXISTS order_event (event_id TEXT PRIMARY KEY, order_id TEXT, broker_order_id TEXT,
    event_type TEXT, payload TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS fills (fill_id TEXT PRIMARY KEY, account_id TEXT, order_id TEXT, symbol TEXT, price REAL,
    qty REAL, fee REAL, tax REAL, transfer_fee REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS position (account_id TEXT, symbol TEXT, qty REAL, avg_cost REAL, frozen_qty REAL,
    updated_ts INTEGER, PRIMARY KEY (account_id, symbol));
CREATE TABLE IF NOT EXISTS audit_event (id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, ref_id TEXT, account_id TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS actor_trade (actor_id TEXT, symbol TEXT, ts INTEGER, side TEXT, price REAL,
    qty REAL, realized_pnl REAL, context TEXT, PRIMARY KEY (actor_id, symbol, ts, side));
CREATE TABLE IF NOT EXISTS experiment (run_id TEXT PRIMARY KEY, kind TEXT, hypothesis TEXT, expr TEXT, params TEXT,
    hypothesis_budget_max INTEGER, n_tests_actual INTEGER, llm_model TEXT, seed INTEGER,
    snapshot_id TEXT, oos_ic REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS agent_run (run_id TEXT PRIMARY KEY, phase TEXT, status TEXT, state TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS job_run (job_id TEXT PRIMARY KEY, kind TEXT, status TEXT, payload TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS trading_rule (rule_id TEXT PRIMARY KEY, market TEXT, board TEXT, product_type TEXT,
    effective_from DATE, effective_to DATE, source_url TEXT, source_confidence TEXT,
    rule_json TEXT, reviewed_by TEXT, reviewed_ts INTEGER);
CREATE TABLE IF NOT EXISTS strategy_lifecycle (strategy TEXT PRIMARY KEY, status TEXT, approved_by TEXT,
    approved_ts INTEGER, monitoring_metrics TEXT, degraded_reason TEXT);
CREATE TABLE IF NOT EXISTS source_audit (id INTEGER PRIMARY KEY, source TEXT, dataset TEXT, status TEXT,
    diff_rate REAL, latency_seconds REAL, checked_ts INTEGER, detail TEXT);
"""


# 设计 v0.5 §6 —— DuckDB 数据库
DUCKDB_DDL = """
CREATE TABLE IF NOT EXISTS instrument (symbol VARCHAR, market VARCHAR, board VARCHAR, product_type VARCHAR,
    list_date DATE, delist_date DATE, status VARCHAR, source VARCHAR, available_at BIGINT, ingested_at BIGINT);
CREATE TABLE IF NOT EXISTS bar (symbol VARCHAR, freq VARCHAR, trade_date DATE, ts BIGINT,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE,
    adj_type VARCHAR, source VARCHAR, available_at BIGINT, received_ts BIGINT, ingested_at BIGINT, as_of BIGINT,
    pit_confidence VARCHAR);
CREATE TABLE IF NOT EXISTS factor_value (factor VARCHAR, factor_version VARCHAR, trade_date DATE, symbol VARCHAR,
    value DOUBLE, available_at BIGINT, computed_at BIGINT, as_of BIGINT, snapshot_id VARCHAR, experiment_run_id VARCHAR);
CREATE TABLE IF NOT EXISTS tick (symbol VARCHAR, event_ts BIGINT, received_ts BIGINT, price DOUBLE, volume DOUBLE);
CREATE TABLE IF NOT EXISTS pit_field (field VARCHAR PRIMARY KEY, source VARCHAR, available_at_rule VARCHAR);
CREATE TABLE IF NOT EXISTS factor_snapshot (snapshot_id VARCHAR PRIMARY KEY, created_ts BIGINT, as_of_cap BIGINT, note VARCHAR);
CREATE TABLE IF NOT EXISTS data_snapshot (snapshot_id VARCHAR, dataset VARCHAR, source VARCHAR,
    as_of_cap BIGINT, row_count BIGINT, checksum VARCHAR, PRIMARY KEY(snapshot_id, dataset));
"""


def _statements(ddl: str) -> Iterable[str]:
    """按分号拆分多条 DDL，剔除纯空白项。"""
    for stmt in ddl.split(";"):
        stripped = stmt.strip()
        if stripped:
            yield stripped


def create_sqlite(conn: sqlite3.Connection) -> None:
    """在 SQLite 连接上建立全部事务库表（幂等，IF NOT EXISTS）。"""
    cur = conn.cursor()
    for stmt in _statements(SQLITE_DDL):
        cur.execute(stmt)
    conn.commit()


def create_duckdb(conn) -> None:
    """在 DuckDB 连接上建立全部数据库表（幂等，IF NOT EXISTS）。

    duckdb 自动提交，无需显式 commit。
    """
    for stmt in _statements(DUCKDB_DDL):
        conn.execute(stmt)
