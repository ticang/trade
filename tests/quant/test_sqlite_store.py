"""SqliteStore 独立写线程 + WAL 测试。

覆盖设计 v0.5 §6 写并发策略：
- 所有写经独立写线程（queue.Queue + threading.Thread，与 asyncio 解耦）
- asyncio 侧 execute 走 put_nowait 非阻塞
- WAL 允许并发读 + 单写
- flush 投 barrier 作为同步点，保证此前所有 exec 已 commit
"""
from __future__ import annotations

import threading

import pytest

from quant.data import schema
from quant.data.sqlite_store import SqliteStore


# account 插入语句（schema 来自 quant.data.schema）
_INSERT_ACCOUNT = (
    "INSERT INTO account (account_id, broker, env, name) VALUES (?, ?, ?, ?)"
)


@pytest.fixture
def store(tmp_path):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    s = SqliteStore(str(tmp_path / "store.db"))
    s.start()
    yield s
    s.stop()


def test_schema_created_on_start(store):
    """start 后 account/position/orders 等事务库表应存在。"""
    rows = store.query_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    names = {r["name"] for r in rows}
    for expected in ("account", "position", "orders", "fills", "audit_event"):
        assert expected in names, f"缺表: {expected}"


def test_wal_mode(store):
    """start 后 journal_mode 应为 wal（小写）。"""
    row = store.query_one("PRAGMA journal_mode")
    assert row[0] == "wal"


def test_write_thread_persists(store):
    """execute 投写任务 → flush → 读回，证明写线程已落盘。"""
    done = store.execute(_INSERT_ACCOUNT, ("acct-1", "xtp", "paper", "测试账户"))
    assert done.wait(timeout=5.0)
    assert store.flush(timeout=5.0)

    row = store.query_one(
        "SELECT account_id, broker, env, name FROM account WHERE account_id = ?",
        ("acct-1",),
    )
    assert row is not None
    assert row["account_id"] == "acct-1"
    assert row["broker"] == "xtp"
    assert row["env"] == "paper"
    assert row["name"] == "测试账户"


def test_concurrent_writes_via_queue(store):
    """10 线程各插多条，flush 后应全部可见、无丢、无死锁。

    所有写都走同一队列被写线程串行消费，主存一致性由 SQLite 保证。
    """
    n_threads = 10
    per_thread = 20

    errors: list[Exception] = []

    def worker(tid: int):
        try:
            for i in range(per_thread):
                store.execute(
                    _INSERT_ACCOUNT,
                    (f"acct-{tid}-{i}", "xtp", "paper", f"账户-{tid}-{i}"),
                )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"并发写抛错: {errors}"
    assert store.flush(timeout=10)

    row = store.query_one("SELECT COUNT(*) AS c FROM account")
    assert row["c"] == n_threads * per_thread


def test_flush_ensures_visibility(store):
    """flush 是同步点：flush 后读必可见。

    不 flush 直接读可能因时序读到空（写线程尚未消费）；但 flush 之后，
    由于 barrier 在队列中排在 exec 之后被同一写线程消费，必保证此前 exec 已 commit。
    """
    store.execute(_INSERT_ACCOUNT, ("acct-flush", "xtp", "paper", "同步点"))
    assert store.flush(timeout=5.0)

    row = store.query_one(
        "SELECT account_id FROM account WHERE account_id = ?",
        ("acct-flush",),
    )
    assert row is not None
    assert row["account_id"] == "acct-flush"


def test_stop_is_idempotent(store):
    """stop 应可重复调用而不抛错。"""
    store.stop()
    store.stop()  # 二次 stop 不抛


def test_start_is_idempotent(tmp_path):
    """重复 start 不应启动第二个写线程。"""
    s = SqliteStore(str(tmp_path / "idem.db"))
    try:
        s.start()
        first_thread = s._thread
        s.start()  # 应被忽略，不替换线程
        assert s._thread is first_thread
    finally:
        s.stop()


def test_query_after_flush_sees_multi_writes(store):
    """多次 execute 后一次 flush，全部写入可见。"""
    for i in range(5):
        store.execute(
            _INSERT_ACCOUNT, (f"acct-multi-{i}", "xtp", "paper", f"多写-{i}")
        )
    assert store.flush(timeout=5.0)
    rows = store.query_all("SELECT account_id FROM account ORDER BY account_id")
    ids = [r["account_id"] for r in rows]
    assert ids == [f"acct-multi-{i}" for i in range(5)]


def test_create_sqlite_compatibility(store):
    """store 用的连接应能被 schema.create_sqlite 幂等再次应用。"""
    # 不抛即通过（IF NOT EXISTS 幂等）
    schema.create_sqlite(store._conn)


def test_stop_drains_pending_writes(tmp_path):
    """stop 必须先 drain 队列：投 N 条写（不 flush）后直接 stop，
    重新打开数据库断言 N 条全在（验证停机不丢写）。

    回归：旧实现 stop 直接 close 连接，队列里未消费的 exec 被丢弃。
    """
    db_path = tmp_path / "drain.db"
    s = SqliteStore(str(db_path))
    s.start()

    n = 50
    # 故意不 flush，制造队列积压
    for i in range(n):
        s.execute(_INSERT_ACCOUNT, (f"acct-drain-{i}", "xtp", "paper", f"drain-{i}"))
    s.stop()  # 停机应 drain 队列，而非丢弃

    # 重新打开同一数据库文件验证持久化
    s2 = SqliteStore(str(db_path))
    s2.start()
    try:
        assert s2.flush(timeout=5.0)
        row = s2.query_one("SELECT COUNT(*) AS c FROM account")
        assert row["c"] == n, f"停机丢写：期望 {n} 条，实际 {row['c']} 条"
    finally:
        s2.stop()


def test_concurrent_reads_during_writes(store):
    """一个写线程持续插入，多个读线程并发 query_all。

    断言：无异常 + 每个读线程观察到的行数单调非减（WAL 快照一致性）+ flush 后最终行数正确。
    """
    total = 100
    write_done = threading.Event()
    errors: list[Exception] = []

    def writer():
        try:
            for i in range(total):
                store.execute(
                    _INSERT_ACCOUNT, (f"acct-crw-{i}", "xtp", "paper", f"crw-{i}")
                )
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            write_done.set()

    def reader(samples: list[int]):
        try:
            last = -1
            while not write_done.is_set():
                rows = store.query_all("SELECT account_id FROM account")
                count = len(rows)
                # WAL 快照：读到的行数不应回退
                assert count >= last, f"行数回退：{last} -> {count}"
                last = count
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    samples: list[int] = []
    readers = [
        threading.Thread(target=reader, args=(samples,)) for _ in range(4)
    ]
    wt = threading.Thread(target=writer)
    for t in readers:
        t.start()
    wt.start()
    wt.join(timeout=10)
    for t in readers:
        t.join(timeout=10)

    assert not errors, f"并发读写抛错: {errors}"
    assert store.flush(timeout=10)
    row = store.query_one("SELECT COUNT(*) AS c FROM account")
    assert row["c"] == total
