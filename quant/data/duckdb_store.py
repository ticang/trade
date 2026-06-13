"""DuckDB 存储层：进程内单写协调。

设计 v0.5 §6 写并发策略：DuckDB 单写进程（盘中独占，盘后交接）。
本模块仅做进程内单写协调——threading.RLock 串行化所有连接访问。

DuckDB 单 connection 非线程安全：多线程同时 execute 同一 connection 会出错。
故读、写均受 RLock 保护（RLock 可重入，write_context 内嵌套调用不死锁）。

跨进程单写交接留 M2 实盘落地。
"""
from __future__ import annotations

import datetime as _dt
import threading
from typing import Any

import duckdb

from quant.data.schema import create_duckdb


class DuckdbStore:
    """DuckDB 单连接存储，RLock 串行化进程内所有读写访问。"""

    def __init__(self, path: str) -> None:
        self._path = path
        # duckdb 单 connection：进程内所有读写经此连接
        self._conn = duckdb.connect(str(path))
        self._wlock = threading.RLock()
        create_duckdb(self._conn)

    def append_bars(self, rows: list[tuple]) -> None:
        """批量 append bar 行（17 列，对齐 schema bar 表）。写持锁。"""
        with self._wlock:
            self._conn.executemany(
                "INSERT INTO bar VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    def query_bars(
        self, symbol: str, start: _dt.date, end: _dt.date
    ) -> list[dict[str, Any]]:
        """按 symbol + trade_date 区间查询 bar，按 trade_date 升序返回 dict 列表。

        DuckDB 单连接非并发安全，读亦持 RLock（与写互斥）。
        """
        with self._wlock:
            cur = self._conn.execute(
                "SELECT * FROM bar WHERE symbol=? AND trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date",
                [symbol, start, end],
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def count_all_bars(self) -> int:
        """返回 bar 表总行数（测试辅助）。持锁。"""
        with self._wlock:
            row = self._conn.execute("SELECT COUNT(*) FROM bar").fetchone()
            return int(row[0])

    def close(self) -> None:
        with self._wlock:
            self._conn.close()

    def write_context(self) -> "_WriteCtx":
        """批量写上下文管理器：持写锁期间可连续 append/query（RLock 可重入）。

        跨进程单写交接留 M2 实盘落地。
        """
        return _WriteCtx(self._wlock)


class _WriteCtx:
    """持 RLock 的上下文管理器；RLock 可重入，嵌套 acquire 不死锁。"""

    def __init__(self, lock: threading.RLock) -> None:
        self._lock = lock

    def __enter__(self) -> threading.RLock:
        self._lock.acquire()
        return self._lock

    def __exit__(self, *exc: object) -> bool:
        self._lock.release()
        return False
