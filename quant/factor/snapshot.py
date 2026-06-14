"""数据快照冻结与可复现（设计 v0.5 §3.3.3 / §4.2.2）。

数据修订→新 as_of；回测绑定 factor_snapshot_id 冻结 as_of 集合，保证可复现。
snapshot 记录 as_of_cap（允许的最大 as_of 时间戳，毫秒）：绑定该 snapshot 的计算
只能用 as_of <= as_of_cap 的数据，修订带来的未来行被裁掉。

factor_snapshot / data_snapshot 两表本属 DuckDB 数据库 schema；本模块在 SQLite 事务库
中按需建表（CREATE IF NOT EXISTS），供回测/实验侧本地冻结与校验使用。两表统一使用
as_of_cap 列（与 factor_snapshot 的 cap 语义一致，按 A4 API 约定）。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import pandas as pd

from quant.data.sqlite_store import SqliteStore


# ---------------------------------------------------------------------------
# DDL（与 §6 DuckDB 同名表保持列一致；首次 create_snapshot 时在 SQLite 建立）
# ---------------------------------------------------------------------------
# data_snapshot 与 factor_snapshot 均用 as_of_cap（cap=上限阈值，§3.3.3）。
_DDL = """
CREATE TABLE IF NOT EXISTS factor_snapshot (
    snapshot_id VARCHAR PRIMARY KEY,
    created_ts BIGINT,
    as_of_cap BIGINT,
    note VARCHAR
);
CREATE TABLE IF NOT EXISTS data_snapshot (
    snapshot_id VARCHAR,
    dataset VARCHAR,
    source VARCHAR,
    as_of_cap BIGINT,
    row_count BIGINT,
    checksum VARCHAR,
    PRIMARY KEY (snapshot_id, dataset)
);
"""


def _ensure_tables(store: SqliteStore) -> None:
    """在 SQLite 中按需建立 factor_snapshot / data_snapshot（幂等）。"""
    for stmt in _DDL.strip().split(";"):
        stripped = stmt.strip()
        if stripped:
            store.execute(stripped)
    store.flush()


# ---------------------------------------------------------------------------
# 确定性 checksum
# ---------------------------------------------------------------------------
def _dataset_checksum(dataset: Any) -> str:
    """数据集确定性 md5 checksum。

    - pandas.DataFrame：列按名排序、行按全部列值排序后 to_csv，保证同数据→同 hash。
    - 其它可迭代对象：转 sorted tuples 后编码。
    """
    if isinstance(dataset, pd.DataFrame):
        df = dataset.copy()
        df = df[sorted(df.columns.tolist())]
        # 行序确定：按全部列排序（NaN 统一处理）
        payload = df.sort_values(by=list(df.columns), kind="mergesort").to_csv(index=False)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()
    # 非帧：按值排序的元组
    try:
        rows = sorted(tuple(r) for r in dataset)
    except TypeError:
        rows = sorted(repr(r) for r in dataset)
    return hashlib.md5(repr(rows).encode("utf-8")).hexdigest()


def _snapshot_id(as_of_cap: int, dataset_checksums: list[tuple[str, str]]) -> str:
    """确定性 snapshot_id：基于 as_of_cap + (dataset 名 + checksum) 组合的 md5。

    同 as_of_cap + 同 datasets 内容 → 同 id（可复现性可验证）。
    """
    payload = str(as_of_cap) + "|" + "|".join(f"{n}:{c}" for n, c in sorted(dataset_checksums))
    h8 = hashlib.md5(payload.encode("utf-8")).hexdigest()[:8]
    return f"snap_{as_of_cap}_{h8}"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def create_snapshot(
    store: SqliteStore,
    as_of_cap: int,
    datasets: dict[str, object],
    note: str = "",
) -> str:
    """冻结数据快照，返回确定性 snapshot_id。

    - 写 factor_snapshot(snapshot_id, created_ts, as_of_cap, note)
    - 对每个 dataset 写 data_snapshot(snapshot_id, dataset, source, as_of_cap,
      row_count, checksum)
    - 幂等：INSERT OR REPLACE；同 as_of_cap + 同 datasets → 同 snapshot_id
    """
    _ensure_tables(store)

    # 先算各 dataset checksum，用于构造确定性 snapshot_id
    items: list[tuple[str, str, int]] = []  # (name, checksum, row_count)
    name_checksum: list[tuple[str, str]] = []
    for name, dataset in datasets.items():
        checksum = _dataset_checksum(dataset)
        row_count = len(dataset) if hasattr(dataset, "__len__") else 0
        items.append((name, checksum, row_count))
        name_checksum.append((name, checksum))

    snapshot_id = _snapshot_id(as_of_cap, name_checksum)
    created_ts = int(time.time() * 1000)

    store.execute(
        "INSERT OR REPLACE INTO factor_snapshot "
        "(snapshot_id, created_ts, as_of_cap, note) VALUES (?, ?, ?, ?)",
        (snapshot_id, created_ts, as_of_cap, note),
    )
    for name, checksum, row_count in items:
        store.execute(
            "INSERT OR REPLACE INTO data_snapshot "
            "(snapshot_id, dataset, source, as_of_cap, row_count, checksum) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, name, "local", as_of_cap, row_count, checksum),
        )
    store.flush()
    return snapshot_id


def _table_exists(store: SqliteStore, name: str) -> bool:
    """SQLite 中表是否存在（读 sqlite_master）。"""
    row = store.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return row is not None


def load_snapshot(store: SqliteStore, snapshot_id: str) -> dict:
    """读回 snapshot 元信息。不存在→KeyError。

    返回 {snapshot_id, as_of_cap, note, created_ts, datasets: {name: {row_count, checksum}}}
    """
    if not _table_exists(store, "factor_snapshot"):
        raise KeyError(snapshot_id)

    row = store.query_one(
        "SELECT snapshot_id, as_of_cap, note, created_ts FROM factor_snapshot "
        "WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    if row is None:
        raise KeyError(snapshot_id)

    data_rows = store.query_all(
        "SELECT dataset, row_count, checksum FROM data_snapshot WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    datasets = {
        r["dataset"]: {"row_count": r["row_count"], "checksum": r["checksum"]}
        for r in data_rows
    }
    return {
        "snapshot_id": row["snapshot_id"],
        "as_of_cap": row["as_of_cap"],
        "note": row["note"],
        "created_ts": row["created_ts"],
        "datasets": datasets,
    }


def bind_panel_to_snapshot(panel: pd.DataFrame, as_of_cap: int) -> pd.DataFrame:
    """过滤 panel 仅保留 as_of（ms）<= as_of_cap 的行（§3.3.3 修订裁剪）。

    回测/因子计算绑定 snapshot 时调用：确保只用冻结 as_of 集合内的数据，修订带来的
    超出 cap 的行被剔除，保证可复现。

    panel 含 as_of 列（int ms 或 datetime，统一转 ms 比较）。返回过滤后的副本。
    """
    if "as_of" not in panel.columns:
        raise KeyError("as_of")

    # as_of 可能是 ms 整数或 datetime；统一转 ms 比较
    if pd.api.types.is_integer_dtype(panel["as_of"]):
        as_of_ms = panel["as_of"].astype("int64")
    else:
        as_of_ms = (
            pd.to_datetime(panel["as_of"], errors="coerce").astype("int64") // 10**6
        )

    mask = as_of_ms <= as_of_cap
    return panel.loc[mask].reset_index(drop=True)
