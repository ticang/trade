import duckdb
from probes.duckdb_perf import materialize_factor_panel, cross_section_query_latency

def test_cross_section_query_under_threshold():
    con = duckdb.connect(database=":memory:")
    materialize_factor_panel(con, n_symbols=1000, n_factors=30, n_days=250)
    latencies = [cross_section_query_latency(con, factor="f_0", day_index=100) for _ in range(20)]
    median_ms = sorted(latencies)[10] * 1000
    assert median_ms < 50, f"median cross-section latency {median_ms:.1f}ms exceeds 50ms"
