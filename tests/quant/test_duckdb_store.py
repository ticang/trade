"""DuckdbStore 进程内单写协调测试。

覆盖设计 v0.5 §6 写并发策略：
- DuckDB 单写进程（盘中独占，盘后交接）
- 本任务做进程内单写协调（threading.RLock 保护写）
- 跨进程单写交接留 M2 实盘落地
"""
from __future__ import annotations

import datetime as _dt
import threading

import pytest

from quant.data.duckdb_store import DuckdbStore


# bar 行：17 列，对齐 schema.DUCKDB_DDL 中的 bar 表
# (symbol, freq, trade_date, ts, open, high, low, close, volume, amount,
#  adj_type, source, available_at, received_ts, ingested_at, as_of, pit_confidence)
def _bar(symbol: str, trade_date: str, close: float = 10.0, freq: str = "1d") -> tuple:
    return (
        symbol, freq, _dt.date.fromisoformat(trade_date), 0,
        close, close, close, close, 1000.0, 10000.0,
        "none", "tushare", 0, 0, 0, 0, "actual",
    )


@pytest.fixture
def store(tmp_path):
    """建一个临时 DuckdbStore，用例结束关闭连接。"""
    s = DuckdbStore(str(tmp_path / "duck.db"))
    yield s
    s.close()


def test_append_and_query_bars(store):
    """append 3 条 bar（同 symbol，不同 trade_date），读回 3 条、字段齐、按 trade_date 排序。"""
    rows = [
        _bar("000001.SZ", "2024-01-03", close=11.0),
        _bar("000001.SZ", "2024-01-01", close=10.0),
        _bar("000001.SZ", "2024-01-02", close=10.5),
    ]
    store.append_bars(rows)

    got = store.query_bars("000001.SZ", _dt.date(2024, 1, 1), _dt.date(2024, 1, 3))
    assert len(got) == 3
    # 按日期升序
    assert [r["trade_date"] for r in got] == [
        _dt.date(2024, 1, 1), _dt.date(2024, 1, 2), _dt.date(2024, 1, 3)
    ]
    # 字段齐：抽样校验关键列
    first = got[0]
    assert first["symbol"] == "000001.SZ"
    assert first["close"] == 10.0
    assert first["pit_confidence"] == "actual"
    assert first["freq"] == "1d"


def test_query_filters_symbol_date(store):
    """append 两个 symbol，query 单 symbol 只返回自己的；日期范围过滤生效。"""
    store.append_bars([
        _bar("000001.SZ", "2024-01-01"),
        _bar("000001.SZ", "2024-01-02"),
        _bar("600000.SH", "2024-01-01"),
    ])

    got = store.query_bars("000001.SZ", _dt.date(2024, 1, 1), _dt.date(2024, 1, 1))
    assert len(got) == 1
    assert got[0]["symbol"] == "000001.SZ"
    assert got[0]["trade_date"] == _dt.date(2024, 1, 1)


def test_concurrent_appends_serialized(store):
    """多线程并发 append 不同 symbol，RLock 串行化写，全部成功、总行数正确、无异常。"""
    symbols = [f"{i:06d}.SZ" for i in range(20)]
    errors: list[BaseException] = []

    def worker(sym: str) -> None:
        try:
            store.append_bars([_bar(sym, "2024-01-01")])
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(s,)) for s in symbols]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert errors == [], f"并发写出现异常: {errors}"
    # 每个线程写 1 行，总行数应等于线程数
    rows = store.query_bars("000000.SZ", _dt.date(2024, 1, 1), _dt.date(2024, 1, 1))
    # 这里查任意一个 symbol 验证存在；总行数用聚合查
    all_rows = store.query_bars("000000.SZ", _dt.date(2024, 1, 1), _dt.date(2024, 1, 1))
    # 用 DuckDB 直接 count
    count = store.count_all_bars()
    assert count == len(symbols)


def test_write_context_holds_lock(store):
    """write_context 内 append/query 不死锁（RLock 可重入）。"""
    with store.write_context():
        store.append_bars([_bar("000001.SZ", "2024-01-01")])
        # write_context 内调 query_bars 也持锁，RLock 可重入，不死锁
        got = store.query_bars("000001.SZ", _dt.date(2024, 1, 1), _dt.date(2024, 1, 1))
        assert len(got) == 1
