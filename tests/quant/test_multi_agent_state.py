"""multi-agent 闭环状态 checkpoint/恢复测试。

设计 v0.5 §4.3.2：自研轻量调度，状态落 agent_run 可从任意轮恢复。
"""
from __future__ import annotations

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.mining.agent_state import AgentState, AgentStateStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "agent.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def state_store(store):
    return AgentStateStore(store)


# ---------------------------------------------------------------------------
# checkpoint + latest
# ---------------------------------------------------------------------------
def test_checkpoint_and_latest(state_store):
    """checkpoint 后 latest 返回同 round/phase/status/state。"""
    st = AgentState(
        run_id="r1",
        round=1,
        phase="hypothesize",
        status="running",
        state={"candidates": ["f1"]},
    )
    state_store.checkpoint(st)
    got = state_store.latest("r1")
    assert got is not None
    assert got.run_id == "r1"
    assert got.round == 1
    assert got.phase == "hypothesize"
    assert got.status == "running"
    assert got.state == {"candidates": ["f1"]}


def test_state_json_roundtrip(state_store):
    """嵌套 dict state 经 JSON 序列化往返后保持相等。"""
    nested = {
        "history": [{"round": 1, "factor": "mom20", "ic": 0.05}],
        "direction": {"bias": "long", "universe": ["000001", "600000"]},
        "void": None,
        "flag": True,
    }
    state_store.checkpoint(
        AgentState("r2", round=3, phase="judge", status="done", state=nested)
    )
    got = state_store.latest("r2")
    assert got is not None
    assert got.state == nested


def test_checkpoint_overwrite(state_store):
    """同 run_id 多次 checkpoint：latest 仅返回最新（更新式，单行）。"""
    state_store.checkpoint(
        AgentState("r3", round=1, phase="hypothesize", status="running", state={})
    )
    state_store.checkpoint(
        AgentState("r3", round=2, phase="compose", status="running", state={"x": 1})
    )
    got = state_store.latest("r3")
    assert got is not None
    assert got.round == 2
    assert got.phase == "compose"
    assert got.state == {"x": 1}
    # 单行：history 长度为 1
    hist = state_store.history("r3")
    assert len(hist) == 1
    assert hist[0].round == 2


def test_resume_none_when_absent(state_store):
    """无记录：resume 返回 None。"""
    assert state_store.resume("nonexistent") is None


def test_resume_returns_latest(state_store):
    """有记录：resume 返回当前最新状态作为恢复点。"""
    state_store.checkpoint(
        AgentState("r4", round=5, phase="iterate", status="paused", state={"k": "v"})
    )
    got = state_store.resume("r4")
    assert got is not None
    assert got.round == 5
    assert got.phase == "iterate"
    assert got.status == "paused"
    assert got.state == {"k": "v"}


def test_phase_progression(state_store):
    """多 phase 顺序 checkpoint：latest.phase 是最后写入的。"""
    for phase in ["hypothesize", "compose", "test"]:
        state_store.checkpoint(
            AgentState("r5", round=1, phase=phase, status="running", state={})
        )
    got = state_store.latest("r5")
    assert got is not None
    assert got.phase == "test"


def test_failed_status_resume_none(state_store):
    """status='failed'：不可恢复，resume 返回 None。"""
    state_store.checkpoint(
        AgentState("r6", round=2, phase="test", status="failed", state={})
    )
    # latest 仍可读到（用于诊断）
    assert state_store.latest("r6") is not None
    # 但 resume 视为不可恢复
    assert state_store.resume("r6") is None
