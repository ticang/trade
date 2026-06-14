"""SQLite 事务库存储：独立写线程 + WAL 并发模型。

设计 v0.5 §6 写并发策略：
- 所有写经独立写线程（threading.Thread + queue.Queue）
- 与 asyncio 解耦：asyncio 侧 execute/put_nowait 非阻塞
- WAL 允许并发读 + 单写，读在调用线程直接复用同一连接
- flush 投 barrier 作为同步点，保证此前所有 exec 已 commit
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from datetime import date, datetime
from typing import Any, Optional, Sequence

from quant.data.schema import create_sqlite

# 队列任务元组的固定槽位
# ("exec", sql, params, done) / ("barrier", None, None, done) / ("stop", None, None, None)
_KIND = 0
_DONE = 3

# 写线程拉取队列任务的最大等待秒数（影响 stop 响应延迟）
_LOOP_TIMEOUT = 0.1


class SqliteStore:
    """SQLite 存储封装：单写线程 + WAL。

    用法：
        s = SqliteStore(path); s.start()
        done = s.execute(sql, params)   # 非阻塞投递，返回 done 事件
        s.flush()                       # 阻塞直到此前所有写已 commit
        row = s.query_one(sql, params)  # 读前应 flush 确保写落盘
        s.stop()                        # 幂等
    """

    def __init__(self, path: str):
        self._path = path
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._stop = threading.Event()
        # 读串行锁：同一 sqlite3 连接上多线程并发 execute→fetchall 会互相截断游标
        # （threadsafety=3 仅在 C 层串行 execute，不保护两步序列），故 query_* 必须互斥
        self._read_lock = threading.Lock()
        # 写线程异常收集（最近一次），避免静默吞掉写失败
        self.last_error: Optional[BaseException] = None

    def start(self) -> None:
        """建立连接 + 表结构并启动写线程。幂等：已启动则直接返回。"""
        if self._thread is not None and self._thread.is_alive():
            return
        # Python 3.12+ 废弃默认 date/datetime adapter，显式注册为 ISO 字符串。
        # SqliteStore 作为事务库唯一入口，此处注册可消除 ~250 条 DeprecationWarning。
        sqlite3.register_adapter(date, lambda d: d.isoformat())
        sqlite3.register_adapter(datetime, lambda dt: dt.isoformat(sep=" "))
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        create_sqlite(self._conn)
        self._thread = threading.Thread(
            target=self._loop, name="sqlite-store-writer", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        """写线程主循环：串行消费队列任务。"""
        assert self._conn is not None
        while not self._stop.is_set():
            try:
                task = self._q.get(timeout=_LOOP_TIMEOUT)
            except queue.Empty:
                continue

            kind = task[_KIND]
            if kind == "exec":
                _, sql, params, done = task
                try:
                    self._conn.execute(sql, params)
                    self._conn.commit()
                except sqlite3.Error as e:
                    self.last_error = e
                    # 回滚以释放写锁
                    try:
                        self._conn.rollback()
                    except BaseException:
                        pass
                    done.set()
                    continue
                done.set()
            elif kind == "barrier":
                # 排在所有先前 exec 之后被同一线程消费，set 即代表此前写已 commit
                task[_DONE].set()
            elif kind == "stop":
                return

    def execute(
        self, sql: str, params: Sequence[Any] = ()
    ) -> threading.Event:
        """非阻塞投递一条写任务，返回 done 事件。

        供 asyncio 侧直接调用：put_nowait 永不阻塞（队列无界）。
        调用方可选 done.wait() 同步等待单条写完成。
        """
        if self._stop.is_set():
            # 已停止：返回一个已 set 的 Event，避免调用方永久阻塞
            evt = threading.Event()
            evt.set()
            return evt
        done = threading.Event()
        self._q.put_nowait(("exec", sql, tuple(params), done))
        return done

    def query_one(
        self, sql: str, params: Sequence[Any] = ()
    ) -> Optional[sqlite3.Row]:
        """读单行。调用前应 flush 以确保写已落盘（应用约定）。

        持 _read_lock 串行：共享连接上并发 execute→fetchone 会破坏游标状态。
        """
        assert self._conn is not None, "query 前必须 start"
        with self._read_lock:
            cur = self._conn.execute(sql, tuple(params))
            return cur.fetchone()

    def query_all(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[sqlite3.Row]:
        """读多行。调用前应 flush 以确保写已落盘（应用约定）。

        持 _read_lock 串行：共享连接上并发 execute→fetchall 会互相截断游标结果
        （观测到结果行被截断），即使 sqlite3 threadsafety=3 也无法避免，因 execute 与
        fetchall 是两步、连接级互斥锁不覆盖中间态。
        """
        assert self._conn is not None, "query 前必须 start"
        with self._read_lock:
            cur = self._conn.execute(sql, tuple(params))
            return cur.fetchall()

    def flush(self, timeout: float = 5.0) -> bool:
        """投 barrier 并等待其完成，保证此前所有 exec 已 commit。

        返回 True 表示 barrier 在超时内完成；False 表示超时。
        """
        if self._stop.is_set():
            return True
        done = threading.Event()
        try:
            self._q.put_nowait(("barrier", None, None, done))
        except queue.Full:  # 无界队列理论不触发，防御性
            return False
        return done.wait(timeout=timeout)

    def stop(self) -> None:
        """停止写线程并关闭连接。幂等。

        停机前先 drain 队列：flush 等待此前所有 exec commit 完成后再关闭连接，
        避免队列中未消费的写被 conn.close() 丢弃。flush 超时仅记日志不阻塞关闭。
        """
        if self._stop.is_set():
            return
        if not self.flush(timeout=5.0):
            # drain 超时：未消费写可能丢失，记日志但不死等
            logging.getLogger(__name__).warning(
                "SqliteStore.stop drain 超时，队列未清空即关闭，可能有写丢失"
            )
        self._stop.set()
        try:
            self._q.put_nowait(("stop", None, None, None))
        except queue.Full:  # 防御性
            pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._conn is not None:
            self._conn.close()
