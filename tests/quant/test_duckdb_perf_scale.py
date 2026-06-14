"""DuckDB 全市场规模性能测试（slow 标记，CI 默认 deselect）。

背景：M-1a 在 1000 标的规模验证 DuckDB 横截面查询 ~1ms；全市场 5300 票规模的外推
留待 M0 实测。本测试验证 5300×250×10 因子规模下，单截面查询仍在可接受预算内
（阈值 50ms，留余量）。
"""
from __future__ import annotations

import time

import duckdb
import pytest

from quant.data.schema import create_duckdb

# 规模参数：5300 标的 × 250 交易日 × 10 因子 ≈ 1300 万行
N_SYMBOLS = 5300
N_DAYS = 250
N_FACTORS = 10
# 截面延迟预算（ms）。M-1a 1000 规模约 1ms，5300 规模留 50ms 余量。
LATENCY_BUDGET_MS = 50.0


@pytest.mark.slow
def test_full_market_cross_section_latency():
    """全市场 5300 标的 × 250 天 × 10 因子，测横截面查询延迟。

    造数用 DuckDB generate_series + cross join 高效生成，避免 Python 逐行插。
    """
    conn = duckdb.connect(":memory:")
    create_duckdb(conn)

    # 高效造数：因子 × 日期 × 标的 cross join，generate_series 驱动
    # 列：factor, factor_version, trade_date, symbol, value,
    #     available_at, computed_at, as_of, snapshot_id, experiment_run_id
    conn.execute(
        f"""
        INSERT INTO factor_value
        SELECT
            'f' || f AS factor,
            'v1' AS factor_version,
            DATE '2024-01-01' + CAST(d - 1 AS INTEGER) AS trade_date,
            's' || LPAD(CAST(s AS VARCHAR), 6, '0') AS symbol,
            RANDOM() * 100 AS value,
            0 AS available_at,
            0 AS computed_at,
            0 AS as_of,
            NULL AS snapshot_id,
            NULL AS experiment_run_id
        FROM generate_series(1, {N_FACTORS}) AS f(f)
        CROSS JOIN generate_series(1, {N_DAYS}) AS d(d)
        CROSS JOIN generate_series(1, {N_SYMBOLS}) AS s(s)
        """
    )

    # 预热：多次跑相同查询，填满 buffer pool、稳定统计，避免首查冷启抖动
    # （5300 规模冷启首查 ~130ms，预热后稳态 ~4ms）
    target_date = "2024-06-01"  # 第 ~110 天，避免边界
    for _ in range(3):
        conn.execute(
            "SELECT symbol, value FROM factor_value WHERE trade_date = ? AND factor = ?",
            [target_date, "f1"],
        ).fetchall()

    # 实测：某 trade_date 某 factor 的全部 symbol 值（标准横截面查询）
    t0 = time.perf_counter()
    rows = conn.execute(
        "SELECT symbol, value FROM factor_value WHERE trade_date = ? AND factor = ?",
        [target_date, "f1"],
    ).fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\n[perf] 5300×250×10 factor_value, cross-section latency = {elapsed_ms:.1f}ms "
          f"(budget {LATENCY_BUDGET_MS}ms)")

    # 截面应含全部 5300 个 symbol
    assert len(rows) == N_SYMBOLS, f"截面行数 {len(rows)} 不等于 {N_SYMBOLS}"
    # 延迟预算
    assert elapsed_ms < LATENCY_BUDGET_MS, (
        f"cross-section latency {elapsed_ms:.1f}ms exceeds {LATENCY_BUDGET_MS}ms budget"
    )

    conn.close()
