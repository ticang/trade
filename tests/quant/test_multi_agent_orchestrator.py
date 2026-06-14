"""multi-agent orchestrator 闭环可恢复测试（设计 v0.5 §4.3.1 3b + §4.3.2）。

MultiAgentOrchestrator 驱动 5 角色闭环（Hypothesizer→Composer→TesterRole→Judge→Iterator），
每轮 checkpoint 到 agent_run，支持从任意轮 resume 续跑，可达 ≥50 轮。

TDD：本文件先于 MultiAgentOrchestrator 实现编写，import 失败为预期红线。
mock LLM（Hypothesizer 子类返回固定 DSL 序列），合成 panel/returns_panel。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.data.sqlite_store import SqliteStore
from quant.mining.agent_state import AgentStateStore
from quant.mining.multi_agent import (
    Composer,
    Hypothesis,
    Hypothesizer,
    Iterator,
    Judge,
    MultiAgentOrchestrator,
    MultiAgentResult,
    TesterRole,
)
from quant.mining.tester import TestConfig, Tester
from quant.mining.tracker import ExperimentTracker


# ---------------------------------------------------------------------------
# fixtures：临时 sqlite + state_store + tracker
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "orch.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def state_store(store):
    return AgentStateStore(store)


@pytest.fixture
def tracker(store):
    return ExperimentTracker(store)


# ---------------------------------------------------------------------------
# mock Hypothesizer：按预设 DSL 序列逐轮返回（可注入异常轮模拟中断）
# ---------------------------------------------------------------------------
class FakeHypothesizer(Hypothesizer):
    """绕过 LLM，按 dsl_sequence 逐轮返回 Hypothesis。raise_at 触发中断。"""

    def __init__(self, dsl_sequence: list[str], raise_at: int | None = None):
        # 不调 super().__init__，避免依赖 LLMClient
        self.dsl_sequence = dsl_sequence
        self.raise_at = raise_at
        self.calls = 0

    def generate(self, topic: str, round_idx: int, feedback: str = "") -> Hypothesis:  # type: ignore[override]
        if self.raise_at is not None and round_idx == self.raise_at:
            self.calls += 1
            raise RuntimeError(f"injected break at round {round_idx}")
        expr = self.dsl_sequence[round_idx % len(self.dsl_sequence)]
        self.calls += 1
        return Hypothesis(hypothesis=f"h{round_idx}", dsl_expr=expr, rationale="mock")


# ---------------------------------------------------------------------------
# 合成 panel：100 symbol × 20 trade_date，含 close；returns 按 close-rank 对齐
# 让 rank(close) 因子与 returns 强相关 → 通过门禁；其它 DSL 弱相关 → archive/iterate
# ---------------------------------------------------------------------------
def _build_panels(seed: int = 7, n_sym: int = 100, n_date: int = 20):
    """造宽格式 panel（symbol/trade_date/close）+ 长格式 returns_panel。

    returns_panel.value 与同截面 close-rank 线性相关 + 小噪声，
    使 rank(close) 因子 IC 强（accept），rank(delay(close,1)) 等时序因子弱（archive/iterate）。
    """
    rng = np.random.default_rng(seed)
    syms = [f"S{i:03d}" for i in range(n_sym)]
    dates = pd.date_range("2024-01-01", periods=n_date, freq="D").astype("int64") // 10**9

    # 每个 symbol 一个基准 close（决定截面排名）
    base = np.linspace(1.0, 100.0, n_sym)
    rng.shuffle(base)
    wide_rows = []
    ret_rows = []
    for j, d in enumerate(dates):
        close_vals = base + rng.normal(0, 0.5, size=n_sym)  # 截面排名稳定
        order = np.argsort(close_vals)
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(n_sym, dtype=float)
        ret_vals = 0.001 * ranked + rng.normal(0, 0.0003, size=n_sym)  # 与 close-rank 强对齐
        for s, c, r in zip(syms, close_vals, ret_vals):
            wide_rows.append((s, int(d), float(c)))
            ret_rows.append((int(d), s, float(r)))
    panel = pd.DataFrame(wide_rows, columns=["symbol", "trade_date", "close"])
    returns_panel = pd.DataFrame(ret_rows, columns=["trade_date", "symbol", "value"])
    return panel, returns_panel


@pytest.fixture(scope="module")
def panels():
    return _build_panels()


# ---------------------------------------------------------------------------
# orchestrator 工厂
# ---------------------------------------------------------------------------
def _make_orchestrator(dsl_sequence, state_store, tracker=None, raise_at=None):
    """5 角色真实 + mock Hypothesizer。Tester 门禁放宽至可被合成数据通过。"""
    h = FakeHypothesizer(dsl_sequence, raise_at=raise_at)
    c = Composer()
    tester = Tester(TestConfig(min_ic=0.02, min_ir=0.3, min_long_short_annual=0.0))
    t = TesterRole(tester)
    j = Judge()
    it = Iterator()
    return MultiAgentOrchestrator(h, c, t, j, it, state_store, tracker)


# ===========================================================================
# 1. test_run_completes_rounds
# ===========================================================================
def test_run_completes_rounds(state_store, panels):
    """max_rounds=3 mock → rounds_completed=3，返回 MultiAgentResult。"""
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("量价动量", panel, returns, max_rounds=3, seed=1)
    assert isinstance(res, MultiAgentResult)
    assert res.rounds_completed == 3


# ===========================================================================
# 2. test_checkpoint_each_round
# ===========================================================================
def test_checkpoint_each_round(state_store, panels):
    """run 后 state_store.latest(run_id) 反映最后轮（phase=iterate, round=最后轮）。"""
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("主题A", panel, returns, max_rounds=3, seed=1)
    st = state_store.latest(res.run_id)
    assert st is not None
    # 最后轮 checkpoint 在 iterate 阶段后，round 为最后一轮（1-based）
    assert st.round == 3
    assert st.status == "done"


# ===========================================================================
# 3. test_accept_collected
# ===========================================================================
def test_accept_collected(state_store, panels):
    """强因子 DSL（rank(close)，returns 对齐）→ accepted 非空。"""
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("强因子", panel, returns, max_rounds=3, seed=1)
    assert len(res.accepted) > 0
    assert all(isinstance(h, Hypothesis) for h in res.accepted)


# ===========================================================================
# 4. test_archive_iterate_tracked
# ===========================================================================
def test_archive_iterate_tracked(state_store, panels):
    """弱因子覆盖 archive 与 iterate 两分支。

    - 非法 DSL（foobar）→ Composer 返回 None → _failed_test_result(ic=0) → archive
    - delay(close,1) → 截面反向，ic≈-0.085（|ic|≥0.01 且未过）→ iterate
    """
    panel, returns = panels
    orch = _make_orchestrator(["foobar(close)", "delay(close,1)"], state_store)
    res = orch.run("弱因子", panel, returns, max_rounds=2, seed=1)
    assert len(res.archived) >= 1   # 第 1 轮非法 DSL → archive
    assert res.iterated >= 1        # 第 2 轮 delay → iterate


# ===========================================================================
# 5. test_resume_from_checkpoint
# ===========================================================================
def test_resume_from_checkpoint(state_store, panels):
    """跑到 raise_at=2 中断 → resume_from 续跑到 4 轮；resumed_from=2，rounds 累计。"""
    panel, returns = panels
    # 第一次：raise_at=2，期望在第 3 轮（round_idx=2）抛异常 → 前 2 轮已完成 checkpoint
    orch = _make_orchestrator(["rank(close)"], state_store, raise_at=2)
    with pytest.raises(RuntimeError):
        orch.run("恢复测试", panel, returns, max_rounds=4, seed=1)
    # 中断发生在第 3 轮 hypothesize（round=3），但 state.rounds_completed=2（已完成 2 轮）
    run_id = "恢复测试_1"
    st = state_store.latest(run_id)
    assert st is not None
    assert st.state.get("rounds_completed") == 2

    # 第二次：resume 续跑（用同 run_id）
    orch2 = _make_orchestrator(["rank(close)"], state_store)
    res = orch2.run("恢复测试", panel, returns, max_rounds=4, seed=1)
    assert res.resumed_from == 2
    assert res.rounds_completed == 4  # 累计到 max_rounds


# ===========================================================================
# 6. test_experiments_logged
# ===========================================================================
def test_experiments_logged(state_store, tracker, panels):
    """tracker 提供 → 每轮 log 一条 experiment；log 数 == rounds。"""
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store, tracker=tracker)
    res = orch.run("日志测试", panel, returns, max_rounds=3, seed=1)
    # experiment 表按 run_id 单行（INSERT OR REPLACE），改用 list_by_kind 计数
    rows = tracker.list_by_kind("mining")
    # run_id 确定性：每轮 run_id 不同（含轮次后缀），故 3 条
    assert len(rows) == 3


# ===========================================================================
# 7. test_run_id_deterministic
# ===========================================================================
def test_run_id_deterministic(state_store, panels):
    """同 topic + seed → 同 run_id。"""
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store)
    r1 = orch.run("同主题", panel, returns, max_rounds=1, seed=42)
    orch2 = _make_orchestrator(["rank(close)"], state_store)
    r2 = orch2.run("同主题", panel, returns, max_rounds=1, seed=42)
    assert r1.run_id == r2.run_id == "同主题_42"


# ===========================================================================
# 8. test_fifty_rounds_mechanism（机制验证，非真实 50）
# ===========================================================================
def test_fifty_rounds_mechanism(state_store, panels):
    """max_rounds=50 mock（即时返回）跑通，rounds_completed=50。

    验证 ≥50 轮机制可达：mock LLM 下每轮即时返回，50 轮快速完成不崩。
    """
    panel, returns = panels
    orch = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("五十轮", panel, returns, max_rounds=50, seed=1)
    assert res.rounds_completed == 50
    # state_store 反映第 50 轮
    st = state_store.latest(res.run_id)
    assert st is not None and st.round == 50
