"""SQLite single-writer queue: all writes serialized via one dedicated thread."""
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass

@dataclass
class _WriteOp:
    sql: str
    params: tuple

class SingleWriterQueue:
    """A dedicated writer thread consuming a queue; callers put_nowait (non-blocking)."""
    def __init__(self, db_path: str, on_lock=None):
        self._on_lock = on_lock
        self._q: queue.Queue[_WriteOp | None] = queue.Queue()
        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            op = self._q.get()
            if op is None:
                break
            try:
                self._conn.execute(op.sql, op.params)
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    # Should not happen with single writer; re-queue and flag.
                    if self._on_lock:
                        self._on_lock()
                    self._q.put(op)
            self._q.task_done()

    def put(self, sql: str, params: tuple = ()) -> None:
        self._q.put_nowait(_WriteOp(sql, params))

    def join(self) -> None:
        self._q.join()

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=5)
        self._conn.close()

def run_concurrent_writes(db_path: str, n_writers: int, writes_per_writer: int) -> dict:
    con_init = sqlite3.connect(db_path)
    con_init.execute("CREATE TABLE IF NOT EXISTS audit_event (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT)")
    con_init.commit(); con_init.close()
    writer = SingleWriterQueue(db_path, on_lock=lambda: locked.__setitem__("count", locked["count"] + 1))
    locked = {"count": 0}
    counter = {"i": 0}
    lock = threading.Lock()

    def worker():
        for _ in range(writes_per_writer):
            with lock:
                counter["i"] += 1
                seq = counter["i"]
            writer.put("INSERT INTO audit_event (ts, kind) VALUES (?, ?)", (seq, "probe"))

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(n_writers)]
    for t in threads: t.start()
    for t in threads: t.join()
    writer.join()
    elapsed = time.perf_counter() - t0
    writer.close()
    return {
        "rows_written": n_writers * writes_per_writer,
        "locked_errors": locked["count"],
        "throughput_rps": (n_writers * writes_per_writer) / elapsed,
        "elapsed_s": elapsed,
    }
