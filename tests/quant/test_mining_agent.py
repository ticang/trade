"""单 agent 假设挖掘闭环测试（设计 v0.5 §4.3.1 3a + §4.3.2）。

闭环：LLM 产假设 + DSL → 解释器算因子值 → Tester 五门 → 入候选库/归档 → tracker 落库。
状态可恢复：每次实验 tracker.log；run_id 确定性 f"{topic}_{seed}_{budget}"。

覆盖点：
- 闭环产出 MineResult，假设数 == budget
- 通过门禁的因子进 candidates
- DSL 未注册算子 → dsl_invalid failure，不 crash
- DSL 求值异常（未知字段）→ dsl_eval_error failure
- 每次假设都 tracker.log（list_by_kind 长度 == budget）
- run_id 确定性：同 (topic, seed, budget) 多次 run 不冲突
- 真实 LLM 端到端（network）

TDD：本文件先于 quant/mining/agent.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from quant.data.sqlite_store import SqliteStore
from quant.dsl.interpreter import evaluate
from quant.dsl.sandbox import Sandbox
from quant.llm.client import LLMClient
from quant.llm.prompt import hypothesis_prompt
from quant.mining.agent import MineResult, SingleAgentMine
from quant.mining.tester import TestConfig, Tester
from quant.mining.tracker import ExperimentTracker


# ---------------------------------------------------------------------------
# 合成 panel：与 Tester/Interpreter 测试一致的长格式 + 字段
# ---------------------------------------------------------------------------
RNG = np.random.default_rng(7)
SYMBOLS = [f"S{i:03d}" for i in range(100)]
N_DATES = 20
DATES = pd.date_range("2024-01-01", periods=N_DATES, freq="D").astype("int64") // 10**9


def _wide_panel(field_values: dict[str, np.ndarray]) -> pd.DataFrame:
    """构造面板：含 symbol/trade_date/各字段。field_values: {field: array[date,symbol]}."""
    rows = []
    for i in range(N_DATES):
        for j, s in enumerate(SYMBOLS):
            row = {"symbol": s, "trade_date": DATES[i]}
            for f, arr in field_values.items():
                row[f] = float(arr[i, j])
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _close_panel() -> pd.DataFrame:
    """close 字段：截面单调 + 截面间时序波动。"""
    base = np.arange(len(SYMBOLS), dtype=float)
    arr = np.empty((N_DATES, len(SYMBOLS)))
    for i in range(N_DATES):
        arr[i] = base + RNG.normal(0, 0.5, size=len(SYMBOLS))
    return _wide_panel({"close": arr})


def _long_panel(value_arr: np.ndarray) -> pd.DataFrame:
    """array[date,symbol] → 长格式 trade_date/symbol/value（给 Tester）。"""
    rows = []
    for i in range(N_DATES):
        for j, s in enumerate(SYMBOLS):
            rows.append((DATES[i], s, float(value_arr[i, j])))
    return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])


def _returns_panel_aligned(close_panel: pd.DataFrame, slope: float = 0.001) -> pd.DataFrame:
    """收益与 close 截面排序正相关，使强因子通过经济门。"""
    close_arr = close_panel.pivot(index="trade_date", columns="symbol", values="close").to_numpy()
    ret_arr = np.empty((N_DATES, len(SYMBOLS)))
    for i in range(N_DATES):
        order = np.argsort(close_arr[i])
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(len(order), dtype=float)
        ret_arr[i] = slope * ranked + RNG.normal(0, slope * 0.3, size=len(order))
    return _long_panel(ret_arr)


# ---------------------------------------------------------------------------
# Mock LLM：complete_json 按序列返回假设
# ---------------------------------------------------------------------------
class _MockLLM:
    """替身 LLMClient：complete_json 按计数器返回假设；model 固定。"""

    def __init__(self, hypotheses: list[dict]):
        self._items = list(hypotheses)
        self._idx = 0
        self.model = "mock-model"

    def complete_json(self, messages: list[dict], **kw) -> dict:
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return item


def _hypothesis(expr: str, hyp: str = "h", params: dict | None = None) -> dict:
    return {"hypothesis": hyp, "dsl_expr": expr, "params": params or {}, "rationale": "r"}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path) -> SqliteStore:
    s = SqliteStore(str(tmp_path / "agent.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def tracker(store) -> ExperimentTracker:
    return ExperimentTracker(store)


@pytest.fixture
def close_panel() -> pd.DataFrame:
    return _close_panel()


@pytest.fixture
def returns_panel(close_panel) -> pd.DataFrame:
    return _returns_panel_aligned(close_panel)


@pytest.fixture
def tester() -> Tester:
    # 放宽 long_short 下限，使构造的强因子稳定通过
    return Tester(TestConfig(min_ic=0.03, min_ir=0.5, min_long_short_annual=0.0))


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_run_loop_produces_result(tester, tracker, close_panel, returns_panel):
    """mock 返回合法 DSL，budget=3 → n_hypotheses=3。"""
    llm = _MockLLM([_hypothesis("rank(ts_delta(close,5))")])
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("动量", close_panel, returns_panel, hypothesis_budget=3, seed=0)
    assert isinstance(res, MineResult)
    assert res.n_hypotheses == 3
    assert res.n_passed + len(res.failures) == 3


def test_passed_factor_collected(tester, tracker, close_panel, returns_panel):
    """强因子 DSL（与收益同序）→ candidates 非空。"""
    # rank(close) 截面单调，与 returns_panel_aligned 同序 → 通过门禁
    llm = _MockLLM([_hypothesis("rank(close)")])
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("动量", close_panel, returns_panel, hypothesis_budget=1, seed=0)
    assert res.n_passed >= 1, f"reasons={res.failures}"
    assert len(res.candidates) >= 1
    cand = res.candidates[0]
    assert "hypothesis" in cand and "expr" in cand and "test_result" in cand


def test_invalid_dsl_skipped(tester, tracker, close_panel, returns_panel):
    """DSL 含未注册算子 foobar → 该次进 failures（dsl_invalid），不 crash。"""
    llm = _MockLLM([_hypothesis("foobar(close)")])
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("动量", close_panel, returns_panel, hypothesis_budget=1, seed=0)
    assert res.n_passed == 0
    assert len(res.failures) == 1
    assert res.failures[0]["reason"] == "dsl_invalid"


def test_eval_error_skipped(tester, tracker, close_panel, returns_panel):
    """DSL 引用不存在字段 nope → dsl_eval_error failure。"""
    llm = _MockLLM([_hypothesis("rank(nope)")])
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("动量", close_panel, returns_panel, hypothesis_budget=1, seed=0)
    assert res.n_passed == 0
    assert len(res.failures) == 1
    assert res.failures[0]["reason"] == "dsl_eval_error"


def test_experiments_logged(tester, tracker, close_panel, returns_panel):
    """每次假设都 tracker.log → list_by_kind('mining') 长度 == budget。"""
    llm = _MockLLM([_hypothesis("rank(close)")])
    agent = SingleAgentMine(llm, tester, tracker)
    agent.run("动量", close_panel, returns_panel, hypothesis_budget=4, seed=0)
    rows = tracker.list_by_kind("mining")
    assert len(rows) == 4


def test_run_id_deterministic(tester, tracker, close_panel, returns_panel):
    """同 (topic, seed, budget) → 同 run_id；不同 seed → 不同 run_id。"""
    llm = _MockLLM([_hypothesis("rank(close)")])
    agent = SingleAgentMine(llm, tester, tracker)
    r1 = agent.run("动量", close_panel, returns_panel, hypothesis_budget=2, seed=0)
    r2 = agent.run("动量", close_panel, returns_panel, hypothesis_budget=2, seed=0)
    r3 = agent.run("动量", close_panel, returns_panel, hypothesis_budget=2, seed=1)
    assert r1.run_id == r2.run_id == "动量_0_2"
    assert r3.run_id == "动量_1_2"


def test_mixed_pass_and_failures(tester, tracker, close_panel, returns_panel):
    """序列含合法/非法/求值错误 → 各自分流，n_hypotheses 仍 == budget。"""
    seq = [
        _hypothesis("rank(close)"),
        _hypothesis("foobar(close)"),
        _hypothesis("rank(nope)"),
    ]
    llm = _MockLLM(seq)
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("动量", close_panel, returns_panel, hypothesis_budget=3, seed=0)
    assert res.n_hypotheses == 3
    reasons = [f["reason"] for f in res.failures]
    assert "dsl_invalid" in reasons
    assert "dsl_eval_error" in reasons


@pytest.mark.network
def test_real_llm_run(tester, tracker, close_panel, returns_panel):
    """真实 LLM 端到端：无凭证 skip；有则 budget=2 跑通不崩。"""
    from quant.llm.client import _load_env

    _load_env()
    if not (
        os.environ.get("LLM_BASE_URL")
        and os.environ.get("LLM_API_KEY")
        and os.environ.get("LLM_MODEL")
    ):
        pytest.skip("LLM 凭证未配置，跳过真实 API 测试")
    llm = LLMClient()
    agent = SingleAgentMine(llm, tester, tracker)
    res = agent.run("低波动反转", close_panel, returns_panel, hypothesis_budget=2, seed=0)
    assert isinstance(res, MineResult)
    assert res.n_hypotheses == 2
