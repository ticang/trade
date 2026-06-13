"""DuckDB cross-section query performance probe."""
import time
import duckdb
from probes.conftest import synth_factor_panel

def materialize_factor_panel(con: duckdb.DuckDBPyConnection, n_symbols: int, n_factors: int, n_days: int) -> None:
    df = synth_factor_panel(n_symbols, n_factors, n_days)
    con.register("panel_df", df)
    con.execute(
        "CREATE TABLE factor_value AS "
        "SELECT factor, CAST(trade_date AS DATE) AS trade_date, symbol, value FROM panel_df"
    )
    con.execute("CREATE INDEX idx_fv ON factor_value(factor, trade_date)")

def cross_section_query_latency(con: duckdb.DuckDBPyConnection, factor: str, day_index: int) -> float:
    # Day_index-th distinct trade_date; query all symbols for one factor on one day.
    con.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _days AS "
        "SELECT DISTINCT trade_date FROM factor_value ORDER BY trade_date"
    )
    target = con.execute(
        "SELECT trade_date FROM _days OFFSET ? LIMIT 1", [day_index]
    ).fetchone()[0]
    t0 = time.perf_counter()
    con.execute(
        "SELECT symbol, value FROM factor_value WHERE factor = ? AND trade_date = ?",
        [factor, target],
    ).fetchall()
    return time.perf_counter() - t0
