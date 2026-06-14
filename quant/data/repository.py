"""Repository 模式：业务语义接口 + 存储特性封装。

设计 v0.5 §3.3.9：Repository 为接口，上层只见业务方法，不见 SQL；
多账户以 account_id 维度隔离（§6 表均带 account_id）。

本模块定义四个 Protocol（Account/Position/Order/Bar）及对应 Sqlite/Duckdb 实现。
SQL 全部封在实现内部，不向上层泄露。
"""
from __future__ import annotations

import time
from typing import Any, Protocol, Sequence

from quant.data.duckdb_store import DuckdbStore
from quant.data.models import Account, Bar
from quant.data.sqlite_store import SqliteStore


# ---------------------------------------------------------------------------
# Protocols —— 业务语义接口，不暴露存储特性
# ---------------------------------------------------------------------------


class AccountRepository(Protocol):
    """账户仓储：账户的增查。"""

    def add(self, account: Account) -> None: ...
    def get(self, account_id: str) -> Account | None: ...
    def list(self) -> list[Account]: ...


class PositionRepository(Protocol):
    """持仓仓储：以 (account_id, symbol) 为主键，多账户隔离。"""

    def upsert(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        avg_cost: float,
        frozen_qty: float = 0.0,
    ) -> None: ...
    def get(self, account_id: str, symbol: str) -> dict | None: ...
    def list_by_account(self, account_id: str) -> list[dict]: ...


class OrderRepository(Protocol):
    """订单仓储：以 order_id 为主键，按 account_id 维度查询。"""

    def insert(self, order: dict) -> None: ...
    def by_account(self, account_id: str) -> list[dict]: ...
    def get(self, order_id: str) -> dict | None: ...


class BarRepository(Protocol):
    """K 线仓储：批量 append + 区间查询。"""

    def append(self, bars: Sequence[Bar]) -> None: ...
    def query(self, symbol: str, start: Any, end: Any) -> list[dict]: ...


# ---------------------------------------------------------------------------
# SQLite 实现
# ---------------------------------------------------------------------------


def _row_to_account(row: Any) -> Account:
    """sqlite3.Row → Account dataclass。"""
    return Account(
        account_id=row["account_id"],
        broker=row["broker"],
        env=row["env"],
        name=row["name"],
    )


class SqliteAccountRepository:
    """账户仓储 SQLite 实现。"""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def add(self, account: Account) -> None:
        # INSERT 后 flush 保证读前已落盘（应用约定）
        self._store.execute(
            "INSERT INTO account (account_id, broker, env, name) "
            "VALUES (?, ?, ?, ?)",
            (account.account_id, account.broker, account.env, account.name),
        )
        self._store.flush()

    def get(self, account_id: str) -> Account | None:
        row = self._store.query_one(
            "SELECT account_id, broker, env, name FROM account WHERE account_id = ?",
            (account_id,),
        )
        return _row_to_account(row) if row is not None else None

    def list(self) -> list[Account]:
        rows = self._store.query_all(
            "SELECT account_id, broker, env, name FROM account"
        )
        return [_row_to_account(r) for r in rows]


class SqlitePositionRepository:
    """持仓仓储 SQLite 实现，PK(account_id, symbol) 天然多账户隔离。"""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def upsert(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        avg_cost: float,
        frozen_qty: float = 0.0,
    ) -> None:
        # INSERT OR REPLACE：同 (acct, symbol) 更新而非报错
        self._store.execute(
            "INSERT OR REPLACE INTO position "
            "(account_id, symbol, qty, avg_cost, frozen_qty, updated_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, symbol, qty, avg_cost, frozen_qty, int(time.time() * 1000)),
        )
        self._store.flush()

    def get(self, account_id: str, symbol: str) -> dict | None:
        row = self._store.query_one(
            "SELECT qty, avg_cost, frozen_qty, updated_ts FROM position "
            "WHERE account_id = ? AND symbol = ?",
            (account_id, symbol),
        )
        if row is None:
            return None
        return {
            "qty": row["qty"],
            "avg_cost": row["avg_cost"],
            "frozen_qty": row["frozen_qty"],
            "updated_ts": row["updated_ts"],
        }

    def list_by_account(self, account_id: str) -> list[dict]:
        rows = self._store.query_all(
            "SELECT account_id, symbol, qty, avg_cost, frozen_qty, updated_ts "
            "FROM position WHERE account_id = ?",
            (account_id,),
        )
        return [
            {
                "account_id": r["account_id"],
                "symbol": r["symbol"],
                "qty": r["qty"],
                "avg_cost": r["avg_cost"],
                "frozen_qty": r["frozen_qty"],
                "updated_ts": r["updated_ts"],
            }
            for r in rows
        ]


# orders 表列序（除 order_id 外），insert 时按此取值，未提供列填 NULL
# 对齐 schema.SQLITE_DDL：account_id, strategy, symbol, side, qty, price,
# status, broker, client_order_id, rule_version, stop_loss, take_profit,
# created_ts, updated_ts, reason
_ORDER_COLS = (
    "account_id, strategy, symbol, side, qty, price, status, broker, "
    "client_order_id, rule_version, stop_loss, take_profit, "
    "created_ts, updated_ts, reason"
)


class SqliteOrderRepository:
    """订单仓储 SQLite 实现，by_account 按 account_id 维度隔离。"""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def insert(self, order: dict) -> None:
        # dict 中缺失的列以 None 补齐，避免列错位
        vals = tuple(order.get(c) for c in _ORDER_COLS.split(", "))
        placeholders = ", ".join("?" for _ in vals)
        self._store.execute(
            f"INSERT INTO orders (order_id, {_ORDER_COLS}) "
            f"VALUES (?, {placeholders})",
            (order["order_id"],) + vals,
        )
        self._store.flush()

    def by_account(self, account_id: str) -> list[dict]:
        rows = self._store.query_all(
            "SELECT order_id, account_id, strategy, symbol, side, qty, price, "
            "status, broker, client_order_id, rule_version, stop_loss, "
            "take_profit, created_ts, updated_ts, reason "
            "FROM orders WHERE account_id = ?",
            (account_id,),
        )
        return [dict(r) for r in rows]

    def get(self, order_id: str) -> dict | None:
        row = self._store.query_one(
            "SELECT order_id, account_id, strategy, symbol, side, qty, price, "
            "status, broker, client_order_id, rule_version, stop_loss, "
            "take_profit, created_ts, updated_ts, reason "
            "FROM orders WHERE order_id = ?",
            (order_id,),
        )
        return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# DuckDB 实现
# ---------------------------------------------------------------------------


# Bar dataclass 字段顺序（17 列，对齐 schema bar 表）
_BAR_FIELDS = (
    "symbol", "freq", "trade_date", "ts",
    "open", "high", "low", "close", "volume", "amount",
    "adj_type", "source", "available_at", "received_ts", "ingested_at",
    "as_of", "pit_confidence",
)


class DuckdbBarRepository:
    """K 线仓储 DuckDB 实现。"""

    def __init__(self, store: DuckdbStore) -> None:
        self._store = store

    def append(self, bars: Sequence[Bar]) -> None:
        # Bar dataclass → 17 列 tuple 列表，对齐 append_bars 入参
        rows = [tuple(getattr(b, f) for f in _BAR_FIELDS) for b in bars]
        self._store.append_bars(rows)

    def query(self, symbol: str, start: Any, end: Any) -> list[dict]:
        return self._store.query_bars(symbol, start, end)
