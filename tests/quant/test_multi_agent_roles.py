"""multi-agent 5 角色闭环测试（设计 v0.5 §4.3.1 3b）。

角色：Hypothesizer → Composer → Tester → Judge → Iterator。
- Hypothesizer：LLM 产假设 + DSL（复用 M3 prompt 模式，逐轮 1 条）
- Composer：Sandbox.validate + interpreter.evaluate → 因子 Series（非法返回 None）
- TesterRole：复用 M3 Tester 五门
- Judge：passed→accept / ic<0.01→archive / 否则 iterate
- Iterator：accept→explore_variants / archive→change_direction / iterate→refine_params

TDD：本文件先于 quant/mining/multi_agent.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant.dsl.interpreter import evaluate
from quant.llm.client import LLMClient
from quant.mining.multi_agent import (
    Composer,
    Hypothesis,
    Hypothesizer,
    Iterator,
    Judge,
    RoundResult,
    TesterRole,
)
from quant.mining.tester import TestConfig, TestResult, Tester


# ---------------------------------------------------------------------------
# mock LLM：复用 test_llm_client 的 fake 模式
# ---------------------------------------------------------------------------
def _make_fake_llm(payload: dict) -> LLMClient:
    """构造绕过凭证检查、complete_json 返回固定 payload 的 LLMClient。"""

    class _FakeMessage:
        def __init__(self, content):
            self.content = content

    class _FakeChoice:
        def __init__(self, content):
            self.message = _FakeMessage(content)

    class _FakeResponse:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]

    class _FakeCompletions:
        def create(self, **kwargs):
            return _FakeResponse(_payload_text)

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self):
            self.chat = _FakeChat()

    _payload_text = json.dumps(payload, ensure_ascii=False)
    c = LLMClient.__new__(LLMClient)
    c.base_url = "http://fake"
    c.api_key = "fake-key"
    c.model = "fake-model"
    c._client = _FakeOpenAI()
    return c


# ---------------------------------------------------------------------------
# 合成 panel（与 test_dsl_interpreter 同款，长格式含 symbol/trade_date）
# ---------------------------------------------------------------------------
def _build_wide_panel() -> pd.DataFrame:
    """宽格式 panel：symbol / trade_date / close / volume（解释器入参形态）。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    rows = []
    for sym, base, step in [("S0", 10.0, 0.5), ("S1", 20.0, -0.5), ("S2", 5.0, 1.0)]:
        for j, d in enumerate(dates):
            close = base + step * j
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": d,
                    "close": close,
                    "volume": close * 1000 + j,
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "trade_date"]).reset_index(drop=True)


@pytest.fixture(scope="module")
def wide_panel() -> pd.DataFrame:
    return _build_wide_panel()


# ===========================================================================
# Hypothesizer：mock LLM → Hypothesis
# ===========================================================================
def test_hypothesizer_generates():
    """mock LLM 返回 {hypothesis, dsl_expr} → Hypothesizer.generate 产 Hypothesis。"""
    llm = _make_fake_llm(
        {"hypothesis": "高成交量股次日有动量", "dsl_expr": "rank(volume)", "rationale": "价量"}
    )
    hyp = Hypothesizer(llm).generate(topic="量价动量", round_idx=0)
    assert isinstance(hyp, Hypothesis)
    assert hyp.hypothesis == "高成交量股次日有动量"
    assert hyp.dsl_expr == "rank(volume)"
    assert hyp.rationale == "价量"


def test_hypothesizer_carries_feedback_in_prompt():
    """带 feedback 时仍能产 Hypothesis（feedback 进 prompt，不影响返回结构）。"""
    llm = _make_fake_llm({"hypothesis": "改进版", "dsl_expr": "ts_mean(close,5)"})
    hyp = Hypothesizer(llm).generate(
        topic="反转", round_idx=2, feedback="上轮 ic 过低，请尝试时序均值"
    )
    assert hyp.dsl_expr == "ts_mean(close,5)"


# ===========================================================================
# Composer：Sandbox.validate + evaluate
# ===========================================================================
def test_composer_evaluates_valid_dsl(wide_panel):
    """合法 DSL → factor Series，与 evaluate 直跑结果一致。"""
    hyp = Hypothesis(hypothesis="x", dsl_expr="rank(close)")
    got = Composer().compose(hyp, wide_panel)
    expected = evaluate("rank(close)", wide_panel)
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_composer_rejects_invalid_dsl(wide_panel):
    """dsl 含未注册算子 → 返回 None（Sandbox 拦截，不抛）。"""
    hyp = Hypothesis(hypothesis="x", dsl_expr="foobar(close)")
    got = Composer().compose(hyp, wide_panel)
    assert got is None


# ===========================================================================
# TesterRole：复用 M3 Tester
# ===========================================================================
def test_tester_role_uses_m3():
    """强因子 → TestResult.passed=True（复用 M3 Tester 五门）。"""
    rng = np.random.default_rng(7)
    syms = [f"S{i:03d}" for i in range(100)]
    dates = (
        pd.date_range("2024-01-01", periods=20, freq="D").astype("int64") // 10**9
    )

    def _strong_panel():
        rows = []
        for i, d in enumerate(dates):
            vals = np.arange(len(syms), dtype=float) + rng.normal(
                0, 0.5, size=len(syms)
            )
            for s, v in zip(syms, vals):
                rows.append((d, s, float(v)))
        return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])

    def _aligned_returns(factor_panel, slope=0.001):
        rows = []
        for i, d in enumerate(dates):
            f_vals = factor_panel[factor_panel["trade_date"] == d][
                "value"
            ].to_numpy()
            order = np.argsort(f_vals)
            ranked = np.empty_like(order, dtype=float)
            ranked[order] = np.arange(len(order), dtype=float)
            vals = slope * ranked + rng.normal(0, slope * 0.3, size=len(order))
            for s, v in zip(syms, vals):
                rows.append((d, s, float(v)))
        return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])

    factor = _strong_panel()
    returns = _aligned_returns(factor)
    tester = Tester(TestConfig(min_ic=0.03, min_ir=0.5, min_long_short_annual=0.0))
    result = TesterRole(tester).test(
        factor, returns, p_value=0.001, hypothesis_budget=10
    )
    assert isinstance(result, TestResult)
    assert result.passed is True


# ===========================================================================
# Judge：三决策
# ===========================================================================
def test_judge_decide_accept():
    """passed=True → 'accept'。"""
    tr = TestResult(
        passed=True,
        ic=0.05,
        ir=1.0,
        bh_fdr_p=0.01,
        novelty_is_novel=True,
        long_short_annual=0.1,
    )
    assert Judge().decide(tr) == "accept"


def test_judge_decide_archive_weak():
    """ic<0.01 且未过 → 'archive'。"""
    tr = TestResult(
        passed=False,
        ic=0.005,
        ir=0.1,
        bh_fdr_p=0.5,
        novelty_is_novel=True,
        long_short_annual=0.0,
    )
    assert Judge().decide(tr) == "archive"


def test_judge_decide_iterate():
    """ic 接近阈值（≥0.01）但未过 → 'iterate'。"""
    tr = TestResult(
        passed=False,
        ic=0.025,
        ir=0.3,
        bh_fdr_p=0.1,
        novelty_is_novel=True,
        long_short_annual=0.0,
    )
    assert Judge().decide(tr) == "iterate"


# ===========================================================================
# Iterator：基于上轮决策给方向
# ===========================================================================
def test_iterator_next_direction_accept():
    """accept → 'explore_variants'。"""
    rr = RoundResult(round=1, judge_decision="accept")
    assert Iterator().next_direction(rr, history=[]) == "explore_variants"


def test_iterator_next_direction_archive():
    """archive → 'change_direction'。"""
    rr = RoundResult(round=1, judge_decision="archive")
    assert Iterator().next_direction(rr, history=[]) == "change_direction"


def test_iterator_next_direction_iterate():
    """iterate → 'refine_params'。"""
    rr = RoundResult(round=1, judge_decision="iterate")
    assert Iterator().next_direction(rr, history=[]) == "refine_params"
