"""实验追踪器：将单次挖掘实验落 experiment 表（§4.3.2）。

每次实验记录：研究主题(kind)、假设预算、假设、DSL 表达式、参数、LLM 版本快照、
seed、样本内外表现(oos_ic)、snapshot_id。params 以 json 文本列存储。
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from quant.data.sqlite_store import SqliteStore

# 列顺序与 experiment 表定义对齐（schema.py）
_COLUMNS = (
    "run_id, kind, hypothesis, expr, params, "
    "hypothesis_budget_max, n_tests_actual, llm_model, seed, "
    "snapshot_id, oos_ic, ts"
)
_PLACEHOLDERS = ",".join(["?"] * 12)


class ExperimentTracker:
    """实验记录读写封装，底层走 SqliteStore 写线程。"""

    def __init__(self, store: SqliteStore):
        self.store = store

    def log(
        self,
        run_id: str,
        kind: str,
        hypothesis: str,
        expr: str,
        params: dict,
        hypothesis_budget: int,
        n_tests: int,
        llm_model: str,
        seed: int,
        snapshot_id: str,
        oos_ic: Optional[float],
    ) -> None:
        """INSERT OR REPLACE 一条实验；params json.dumps；ts=毫秒时间戳；flush 落盘。"""
        self.store.execute(
            f"INSERT OR REPLACE INTO experiment({_COLUMNS}) VALUES({_PLACEHOLDERS})",
            (
                run_id,
                kind,
                hypothesis,
                expr,
                json.dumps(params, ensure_ascii=False),
                hypothesis_budget,
                n_tests,
                llm_model,
                seed,
                snapshot_id,
                oos_ic,
                int(time.time() * 1000),
            ),
        )
        self.store.flush()

    def _row_to_dict(self, row: Any) -> Optional[dict]:
        """sqlite3.Row → dict，params 反序列化。row 为 None 时返回 None。"""
        if row is None:
            return None
        d = dict(row)
        d["params"] = json.loads(d["params"]) if d.get("params") else {}
        return d

    def get(self, run_id: str) -> Optional[dict]:
        """读单条；params 反序列化回 dict；不存在返回 None。"""
        row = self.store.query_one(
            f"SELECT {_COLUMNS} FROM experiment WHERE run_id=?", (run_id,)
        )
        return self._row_to_dict(row)

    def list_by_kind(self, kind: str) -> list[dict]:
        """按 kind 过滤，params 反序列化。"""
        rows = self.store.query_all(
            f"SELECT {_COLUMNS} FROM experiment WHERE kind=?", (kind,)
        )
        return [self._row_to_dict(r) for r in rows]  # type: ignore[list-item]

    def count_passed(self, min_oos_ic: float = 0.0) -> int:
        """统计 oos_ic >= min_oos_ic 的实验数（通过门禁的近似计数，NULL 不计）。"""
        row = self.store.query_one(
            "SELECT COUNT(*) AS n FROM experiment WHERE oos_ic >= ?", (min_oos_ic,)
        )
        return int(row["n"]) if row is not None else 0
