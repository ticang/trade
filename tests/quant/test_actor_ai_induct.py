"""主体行为学习 Task 3 测试：AI 归纳（设计 v0.5 §4.9.3 路径2）。

LLM 读主体高胜率 trades 样本 → 归纳高胜率条件 → 候选 DSL 因子/规则。

覆盖点：
- induct 产出 candidates（mock 返回合法 DSL → 通过沙箱 + 新颖性 → candidates 非空）
- 未注册算子（foobar(x)）→ rejected(reason='dsl_invalid')
- 与已知因子高相关 → rejected(reason='novelty_fail')
- budget 循环：mock 返回 N 条 → n_samples=N，candidates+rejected 合计=N
- prompt 携带主体摘要（kind + 样本 symbol/sector）
- 真实 LLM 端到端（network，无凭证 skip）

TDD：本文件先于 quant/actor/ai_induct.py 实现，import 失败为预期红线。
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from quant.actor.model import Actor, ActorKind, ActorTrade
from quant.actor.ai_induct import AIInduct, InductResult


# ---------------------------------------------------------------------------
# Mock LLM：complete_json 按序列返回假设，并捕获 messages
# ---------------------------------------------------------------------------
class _MockLLM:
    """替身 LLMClient：complete_json 按计数器返回候选；model 固定。

    记录每次调用收到的 messages，供 prompt 摘要断言。
    """

    def __init__(self, items: list[dict]):
        self._items = list(items)
        self._idx = 0
        self.model = "mock-model"
        self.calls: list[list[dict]] = []

    def complete_json(self, messages: list[dict], **kw) -> dict:
        self.calls.append(messages)
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return item


def _candidate(expr: str, hyp: str = "h", rationale: str = "r") -> dict:
    return {"hypothesis": hyp, "dsl_expr": expr, "rationale": rationale}


def _make_actor(n_trades: int = 4, kind: ActorKind = ActorKind.HOT_MONEY) -> Actor:
    """构造一个含若干高胜率 trades 的主体（symbol/sector 多样）。"""
    sectors = ["电子", "医药", "电子", "消费"]
    symbols = ["S001", "S002", "S003", "S004"]
    actor = Actor(id="A1", kind=kind)
    base = datetime(2024, 1, 1)
    for i in range(n_trades):
        actor.add_trade(
            ActorTrade(
                symbol=symbols[i % len(symbols)],
                time=base.replace(day=i + 1),
                side="buy" if i % 2 == 0 else "sell",
                price=10.0 + i,
                volume=1000.0,
                realized_pnl=10.0 if i % 2 == 0 else 0.0,
                context={"sector": sectors[i % len(sectors)]},
            )
        )
    return actor


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_induct_produces_candidates():
    """mock 返回合法 DSL → candidates 非空。"""
    llm = _MockLLM([_candidate("rank(ts_delta(close,5))")])
    inductor = AIInduct(llm)
    res = inductor.induct(_make_actor(), budget=1)
    assert isinstance(res, InductResult)
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c["dsl_expr"] == "rank(ts_delta(close,5))"
    assert "hypothesis" in c and "rationale" in c
    assert res.n_samples == 1


def test_invalid_dsl_rejected():
    """mock 返回未注册算子 foobar(x) → rejected reason='dsl_invalid'。"""
    llm = _MockLLM([_candidate("foobar(x)")])
    inductor = AIInduct(llm)
    res = inductor.induct(_make_actor(), budget=1)
    assert res.candidates == []
    assert len(res.rejected) == 1
    assert res.rejected[0]["reason"] == "dsl_invalid"
    assert res.rejected[0]["dsl_expr"] == "foobar(x)"


def test_novelty_rejected():
    """候选 DSL 与已知因子表达式重复 → rejected reason='novelty_fail'。

    ai_induct 阶段无 panel 可评估候选 DSL，故对 known_factor_panels（已知 DSL
    表达式清单）做归一化字符串比对：候选表达式命中已知清单 → 视为复述 → 拒。
    """
    llm = _MockLLM([_candidate("rank(close)")])
    inductor = AIInduct(llm)
    res = inductor.induct(
        _make_actor(),
        known_factor_panels=["rank(close)"],
        budget=1,
    )
    assert res.candidates == []
    assert len(res.rejected) == 1
    assert res.rejected[0]["reason"] == "novelty_fail"
    assert res.rejected[0]["dsl_expr"] == "rank(close)"


def test_budget_loop():
    """budget=3 mock 返回 3 条 → n_samples=3，candidates+rejected 合计=3。"""
    items = [
        _candidate("rank(ts_delta(close,5))"),
        _candidate("foobar(x)"),
        _candidate("ts_mean(volume,10)"),
    ]
    llm = _MockLLM(items)
    inductor = AIInduct(llm)
    res = inductor.induct(_make_actor(), budget=3)
    assert res.n_samples == 3
    assert len(res.candidates) + len(res.rejected) == 3
    # 第 2 条 foobar → rejected；第 1/3 合法且新颖 → candidates
    assert len(res.rejected) == 1
    assert res.rejected[0]["dsl_expr"] == "foobar(x)"
    assert len(res.candidates) == 2


def test_prompt_includes_actor_summary():
    """prompt 必须含主体 kind + 样本摘要（symbol/sector）。"""
    llm = _MockLLM([_candidate("rank(close)")])
    inductor = AIInduct(llm)
    actor = _make_actor()
    inductor.induct(actor, budget=1)
    assert len(llm.calls) == 1
    user_text = llm.calls[0][-1]["content"]
    # 含主体类型
    assert "hot_money" in user_text or "HOT_MONEY" in user_text
    # 含样本摘要：symbol 或 sector 之一
    assert "S001" in user_text or "电子" in user_text
    # 含可用算子清单
    assert "rank" in user_text


@pytest.mark.network
def test_real_llm_induct():
    """真实 LLM 端到端：无凭证 skip；有则 budget=2 跑通返回 InductResult。"""
    from quant.llm.client import LLMClient, _load_env

    _load_env()
    if not (
        os.environ.get("LLM_BASE_URL")
        and os.environ.get("LLM_API_KEY")
        and os.environ.get("LLM_MODEL")
    ):
        pytest.skip("LLM 凭证未配置，跳过真实 API 测试")
    llm = LLMClient()
    inductor = AIInduct(llm)
    res = inductor.induct(_make_actor(), budget=2)
    assert isinstance(res, InductResult)
    assert res.n_samples == 2
