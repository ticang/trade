"""multi-agent 闭环状态 checkpoint/恢复。

设计 v0.5 §4.3.2：自研轻量调度（函数调用 + 状态机），状态落 agent_run 表，
可从任意轮恢复。agent_run 单行 per run_id（更新式），每轮 checkpoint 覆写当前状态。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from quant.data.sqlite_store import SqliteStore

# 不可恢复的终态：resume 视为无恢复点
_NON_RESUMABLE_STATUS = "failed"


@dataclass
class AgentState:
    """闭环一轮的状态快照。"""

    run_id: str
    round: int  # 当前轮次
    phase: str  # 'hypothesize'|'compose'|'test'|'judge'|'iterate'
    status: str  # 'running'|'paused'|'done'|'failed'
    state: dict  # 任意 checkpoint 状态（候选/历史/方向）


class AgentStateStore:
    """agent_run 表读写封装：checkpoint 落库，latest/resume 读出。"""

    def __init__(self, store: SqliteStore):
        self.store = store

    def checkpoint(self, state: AgentState) -> None:
        """落 agent_run：INSERT OR REPLACE（run_id, phase, status, state, ts）。每轮调。

        round 不在 agent_run schema 内，随 state JSON 一并持久化（键 _round）。
        """
        payload = dict(state.state)
        payload["_round"] = state.round
        self.store.execute(
            "INSERT OR REPLACE INTO agent_run(run_id, phase, status, state, ts) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                state.run_id,
                state.phase,
                state.status,
                json.dumps(payload, ensure_ascii=False),
                int(time.time()),
            ),
        )
        self.store.flush()

    def latest(self, run_id: str) -> Optional[AgentState]:
        """读 run_id 最新状态（agent_run 单行 per run_id）。无 → None。"""
        row = self.store.query_one(
            "SELECT run_id, phase, status, state FROM agent_run WHERE run_id=?",
            (run_id,),
        )
        if row is None:
            return None
        return _row_to_state(row)

    def resume(self, run_id: str) -> Optional[AgentState]:
        """恢复点入口：无记录或 status=failed → None。"""
        got = self.latest(run_id)
        if got is None or got.status == _NON_RESUMABLE_STATUS:
            return None
        return got

    def history(self, run_id: str) -> list[AgentState]:
        """单行更新式：返回 [latest] 或 []。"""
        got = self.latest(run_id)
        return [got] if got is not None else []


def _row_to_state(row) -> AgentState:
    """sqlite3.Row → AgentState，反序列化 state JSON，取回 _round。"""
    raw = json.loads(row["state"]) if row["state"] else {}
    rnd = raw.pop("_round", 0)
    return AgentState(
        run_id=row["run_id"],
        round=rnd,
        phase=row["phase"],
        status=row["status"],
        state=raw,
    )
