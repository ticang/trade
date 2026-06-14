"""实验追踪器测试：覆盖落库 / params 往返 / 按类查询 / 通过计数 / 幂等 / NULL 处理。

对应 M3 §4.3.2 实验追踪：每次实验记录研究主题、假设预算、假设、DSL 表达式、
参数、LLM 版本快照、seed、样本内外表现，落 experiment 表。
"""
from __future__ import annotations

import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.mining.tracker import ExperimentTracker


@pytest.fixture
def tracker(tmp_path) -> ExperimentTracker:
    """临时库造 SqliteStore + Tracker。"""
    store = SqliteStore(str(tmp_path / "exp.db"))
    store.start()
    yield ExperimentTracker(store)
    store.stop()


def test_log_and_get(tracker: ExperimentTracker) -> None:
    """log 一条 → get 返回字段完整。"""
    tracker.log(
        run_id="r1",
        kind="mining",
        hypothesis="新闻情绪正向 → 次日超额",
        expr="rank(news_sentiment_pos)",
        params={"window": 5},
        hypothesis_budget=20,
        n_tests=3,
        llm_model="gpt-4o-2024-08-06",
        seed=42,
        snapshot_id="snap-001",
        oos_ic=0.05,
    )
    row = tracker.get("r1")
    assert row is not None
    assert row["run_id"] == "r1"
    assert row["kind"] == "mining"
    assert row["hypothesis"] == "新闻情绪正向 → 次日超额"
    assert row["expr"] == "rank(news_sentiment_pos)"
    assert row["params"] == {"window": 5}
    assert row["hypothesis_budget_max"] == 20
    assert row["n_tests_actual"] == 3
    assert row["llm_model"] == "gpt-4o-2024-08-06"
    assert row["seed"] == 42
    assert row["snapshot_id"] == "snap-001"
    assert row["oos_ic"] == pytest.approx(0.05)


def test_params_roundtrip(tracker: ExperimentTracker) -> None:
    """嵌套 params dict 经 json 序列化落库、get 反序列化回相等。"""
    nested = {
        "filters": {"board": "主板", "cap_min": 5_000_000},
        "windows": [1, 5, 20],
        "weights": {"a": 0.4, "b": 0.6},
    }
    tracker.log(
        run_id="r2",
        kind="mining",
        hypothesis="h",
        expr="e",
        params=nested,
        hypothesis_budget=10,
        n_tests=1,
        llm_model="m",
        seed=1,
        snapshot_id="s",
        oos_ic=0.0,
    )
    assert tracker.get("r2")["params"] == nested


def test_list_by_kind(tracker: ExperimentTracker) -> None:
    """list_by_kind 仅返回匹配 kind 的行。"""
    base = dict(
        hypothesis="h", expr="e", params={}, hypothesis_budget=1, n_tests=1,
        llm_model="m", seed=0, snapshot_id="s", oos_ic=None,
    )
    tracker.log(run_id="m1", kind="mining", **base)
    tracker.log(run_id="m2", kind="mining", **base)
    tracker.log(run_id="b1", kind="baseline", **base)

    rows = tracker.list_by_kind("mining")
    assert {r["run_id"] for r in rows} == {"m1", "m2"}
    assert len(rows) == 2


def test_count_passed(tracker: ExperimentTracker) -> None:
    """count_passed(min_oos_ic) 仅计 oos_ic >= 阈值的实验数。"""
    base = dict(
        kind="mining", hypothesis="h", expr="e", params={},
        hypothesis_budget=1, n_tests=1, llm_model="m", seed=0, snapshot_id="s",
    )
    tracker.log(run_id="a", oos_ic=0.01, **base)  # 低于阈值
    tracker.log(run_id="b", oos_ic=0.03, **base)  # 恰好等于
    tracker.log(run_id="c", oos_ic=0.07, **base)  # 高于
    tracker.log(run_id="d", oos_ic=None, **base)  # NULL 不计

    assert tracker.count_passed(0.03) == 2


def test_log_idempotent(tracker: ExperimentTracker) -> None:
    """同 run_id 两次 log：INSERT OR REPLACE 后仅 1 行。"""
    payload = dict(
        kind="mining", hypothesis="h", expr="e", params={},
        hypothesis_budget=1, n_tests=1, llm_model="m", seed=0,
        snapshot_id="s", oos_ic=0.05,
    )
    tracker.log(run_id="dup", **payload)
    tracker.log(run_id="dup", **payload)

    rows = tracker.list_by_kind("mining")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "dup"


def test_oos_ic_null(tracker: ExperimentTracker) -> None:
    """oos_ic=None → 落 SQL NULL，get 返回 None。"""
    tracker.log(
        run_id="null1",
        kind="mining",
        hypothesis="h",
        expr="e",
        params={},
        hypothesis_budget=1,
        n_tests=1,
        llm_model="m",
        seed=0,
        snapshot_id="s",
        oos_ic=None,
    )
    row = tracker.get("null1")
    assert row is not None
    assert row["oos_ic"] is None
