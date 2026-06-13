import sqlite3
from probes.sqlite_write import SingleWriterQueue, run_concurrent_writes

def test_concurrent_writes_no_lock_and_meets_throughput(tmp_path):
    db = tmp_path / "test.db"
    stats = run_concurrent_writes(db_path=str(db), n_writers=8, writes_per_writer=125)
    assert stats["locked_errors"] == 0, "database is locked occurred"
    assert stats["rows_written"] == 1000
    assert stats["throughput_rps"] > 5000, f"throughput {stats['throughput_rps']:.0f} rps < 5000"
    # Verify rows persisted
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1000
