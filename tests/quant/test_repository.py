"""Repository 模式测试：多账户隔离 + 业务语义封装。

覆盖设计 v0.5 §3.3.9：Repository 为接口，业务语义不暴露存储特性；
多账户以 account_id 维度隔离（§6 表均带 account_id）。

TDD：本文件先于 repository.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

import datetime as _dt

import pytest

from quant.data.duckdb_store import DuckdbStore
from quant.data.models import Account, Bar
from quant.data.repository import (
    DuckdbBarRepository,
    SqliteAccountRepository,
    SqliteOrderRepository,
    SqlitePositionRepository,
)
from quant.data.sqlite_store import SqliteStore


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite(tmp_path):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    s = SqliteStore(str(tmp_path / "repo.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def duckdb(tmp_path):
    """建一个临时 DuckdbStore，用例结束关闭连接。"""
    s = DuckdbStore(str(tmp_path / "repo.duckdb"))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# AccountRepository
# ---------------------------------------------------------------------------


def test_account_add_get(sqlite):
    """add 写入 → get 按 account_id 取回，字段全等。"""
    repo = SqliteAccountRepository(sqlite)
    acct = Account(account_id="acct-1", broker="xtp", env="paper", name="测试账户1")
    repo.add(acct)

    got = repo.get("acct-1")
    assert got is not None
    assert got.account_id == "acct-1"
    assert got.broker == "xtp"
    assert got.env == "paper"
    assert got.name == "测试账户1"


def test_account_get_missing_returns_none(sqlite):
    """get 不存在的 account_id 返回 None，不抛异常。"""
    repo = SqliteAccountRepository(sqlite)
    assert repo.get("nope") is None


def test_account_list(sqlite):
    """list 返回全部账户。"""
    repo = SqliteAccountRepository(sqlite)
    repo.add(Account("acct-1", "xtp", "paper", "A"))
    repo.add(Account("acct-2", "xt", "live", "B"))

    accts = repo.list()
    assert len(accts) == 2
    ids = {a.account_id for a in accts}
    assert ids == {"acct-1", "acct-2"}


# ---------------------------------------------------------------------------
# PositionRepository
# ---------------------------------------------------------------------------


def test_position_upsert_and_get(sqlite):
    """upsert 写入 → get 取回 dict，字段对齐。"""
    repo = SqlitePositionRepository(sqlite)
    repo.upsert("acct-1", "600519.SH", qty=100.0, avg_cost=1800.0, frozen_qty=10.0)

    got = repo.get("acct-1", "600519.SH")
    assert got is not None
    assert got["qty"] == 100.0
    assert got["avg_cost"] == 1800.0
    assert got["frozen_qty"] == 10.0
    assert "updated_ts" in got


def test_position_upsert_idempotent_update(sqlite):
    """重复 upsert 同 (acct, symbol) 应更新而非报错。"""
    repo = SqlitePositionRepository(sqlite)
    repo.upsert("acct-1", "600519.SH", qty=100.0, avg_cost=1800.0)
    # 第二次：数量与成本变更，不应触发主键冲突
    repo.upsert("acct-1", "600519.SH", qty=200.0, avg_cost=1850.0, frozen_qty=20.0)

    got = repo.get("acct-1", "600519.SH")
    assert got is not None
    assert got["qty"] == 200.0
    assert got["avg_cost"] == 1850.0
    assert got["frozen_qty"] == 20.0


def test_position_get_missing_returns_none(sqlite):
    """get 不存在的 (acct, symbol) 返回 None。"""
    repo = SqlitePositionRepository(sqlite)
    assert repo.get("acct-1", "000001.SZ") is None


def test_position_list_by_account(sqlite):
    """list_by_account 只返回该账户的持仓。"""
    repo = SqlitePositionRepository(sqlite)
    repo.upsert("acct-1", "600519.SH", qty=100.0, avg_cost=1800.0)
    repo.upsert("acct-1", "000001.SZ", qty=200.0, avg_cost=12.0)
    repo.upsert("acct-2", "600519.SH", qty=300.0, avg_cost=1800.0)

    rows = repo.list_by_account("acct-1")
    assert len(rows) == 2
    symbols = {r["symbol"] for r in rows}
    assert symbols == {"600519.SH", "000001.SZ"}


# ---------------------------------------------------------------------------
# 多账户隔离（核心验收）
# ---------------------------------------------------------------------------


def test_position_multi_account_isolation(sqlite):
    """acct1 的持仓 acct2 查不到；list_by_account 不串账户。"""
    repo = SqlitePositionRepository(sqlite)
    repo.upsert("acct-1", "600519.SH", qty=100.0, avg_cost=1800.0)

    # acct1 能查到，acct2 同 symbol 查不到
    assert repo.get("acct-1", "600519.SH") is not None
    assert repo.get("acct-2", "600519.SH") is None

    # acct2 自己写一条不同 symbol
    repo.upsert("acct-2", "000001.SZ", qty=200.0, avg_cost=12.0)
    acct1_rows = repo.list_by_account("acct-1")
    acct2_rows = repo.list_by_account("acct-2")
    assert {r["symbol"] for r in acct1_rows} == {"600519.SH"}
    assert {r["symbol"] for r in acct2_rows} == {"000001.SZ"}


# ---------------------------------------------------------------------------
# OrderRepository
# ---------------------------------------------------------------------------


def _order(order_id: str, account_id: str, symbol: str = "600519.SH") -> dict:
    """构造一笔订单 dict（字段对齐 orders 表）。"""
    return {
        "order_id": order_id,
        "account_id": account_id,
        "strategy": "demo",
        "symbol": symbol,
        "side": "buy",
        "qty": 100.0,
        "price": 1800.0,
        "status": "new",
        "broker": "xtp",
        "client_order_id": f"c-{order_id}",
        "created_ts": 1700000000,
        "updated_ts": 1700000000,
    }


def test_order_insert_and_get(sqlite):
    """insert 写入 → get 按 order_id 取回。"""
    repo = SqliteOrderRepository(sqlite)
    repo.insert(_order("o-1", "acct-1"))

    got = repo.get("o-1")
    assert got is not None
    assert got["order_id"] == "o-1"
    assert got["account_id"] == "acct-1"
    assert got["symbol"] == "600519.SH"
    assert got["status"] == "new"


def test_order_get_missing_returns_none(sqlite):
    """get 不存在的 order_id 返回 None。"""
    repo = SqliteOrderRepository(sqlite)
    assert repo.get("nope") is None


def test_order_by_account(sqlite):
    """by_account 只返回该账户的订单。"""
    repo = SqliteOrderRepository(sqlite)
    repo.insert(_order("o-1", "acct-1"))
    repo.insert(_order("o-2", "acct-1"))
    repo.insert(_order("o-3", "acct-2"))

    acct1 = repo.by_account("acct-1")
    acct2 = repo.by_account("acct-2")
    assert {o["order_id"] for o in acct1} == {"o-1", "o-2"}
    assert {o["order_id"] for o in acct2} == {"o-3"}


def test_order_multi_account_isolation(sqlite):
    """acct1 的订单 acct2 by_account 查不到。"""
    repo = SqliteOrderRepository(sqlite)
    repo.insert(_order("o-1", "acct-1"))

    # acct2 视角下查不到 acct1 的订单
    assert repo.by_account("acct-2") == []
    # 但 get 跨账户仍可按 order_id 取（order_id 全局唯一）
    assert repo.get("o-1") is not None


# ---------------------------------------------------------------------------
# BarRepository
# ---------------------------------------------------------------------------


def _bar(symbol: str, trade_date: str, close: float = 10.0) -> Bar:
    """构造一根日 K，字段对齐 Bar dataclass（17 列）。"""
    return Bar(
        symbol=symbol,
        freq="1d",
        trade_date=_dt.date.fromisoformat(trade_date),
        ts=0,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
        amount=10000.0,
        adj_type="none",
        source="tushare",
        available_at=0,
        received_ts=0,
        ingested_at=0,
        as_of=0,
        pit_confidence="live",
    )


def test_bar_append_and_query(duckdb):
    """append 多根 Bar → query 按 symbol+区间返回，字段对齐。"""
    repo = DuckdbBarRepository(duckdb)
    repo.append([
        _bar("600519.SH", "2024-01-01", close=1800.0),
        _bar("600519.SH", "2024-01-02", close=1810.0),
        _bar("600519.SH", "2024-01-03", close=1820.0),
    ])

    got = repo.query(
        "600519.SH",
        _dt.date(2024, 1, 1),
        _dt.date(2024, 1, 3),
    )
    assert len(got) == 3
    assert [r["trade_date"] for r in got] == [
        _dt.date(2024, 1, 1),
        _dt.date(2024, 1, 2),
        _dt.date(2024, 1, 3),
    ]
    assert [r["close"] for r in got] == [1800.0, 1810.0, 1820.0]


def test_bar_query_filters_symbol(duckdb):
    """query 指定 symbol 不返回其他 symbol 的数据。"""
    repo = DuckdbBarRepository(duckdb)
    repo.append([
        _bar("600519.SH", "2024-01-01", close=1800.0),
        _bar("000001.SZ", "2024-01-01", close=12.0),
    ])

    got = repo.query("600519.SH", _dt.date(2024, 1, 1), _dt.date(2024, 1, 2))
    assert len(got) == 1
    assert got[0]["symbol"] == "600519.SH"
    assert got[0]["close"] == 1800.0


def test_bar_query_range_excludes_outside(duckdb):
    """query 区间外的数据不返回。"""
    repo = DuckdbBarRepository(duckdb)
    repo.append([
        _bar("600519.SH", "2024-01-01", close=1800.0),
        _bar("600519.SH", "2024-01-15", close=1850.0),
        _bar("600519.SH", "2024-01-20", close=1860.0),
    ])

    got = repo.query(
        "600519.SH",
        _dt.date(2024, 1, 10),
        _dt.date(2024, 1, 16),
    )
    assert len(got) == 1
    assert got[0]["trade_date"] == _dt.date(2024, 1, 15)
