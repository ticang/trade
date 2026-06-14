"""multi-agent 5 角色闭环（设计 v0.5 §4.3.1 3b）。

角色链：Hypothesizer → Composer → Tester → Judge → Iterator。
- Hypothesizer：LLM 产假设 + DSL（逐轮 1 条，复用 M3 prompt 模式）
- Composer：Sandbox.validate + interpreter.evaluate → 因子 Series（非法返回 None）
- TesterRole：复用 M3 Tester 五门
- Judge：passed→accept / ic<0.01→archive / 否则 iterate
- Iterator：accept→explore_variants / archive→change_direction / iterate→refine_params

各角色低耦合、职责单一，由上层调度串联（状态机见 agent_state.py）。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant.dsl.interpreter import DslError, evaluate
from quant.dsl.sandbox import Sandbox
from quant.llm.client import LLMClient
from quant.llm.prompt import hypothesis_prompt
from quant.mining.tester import TestResult, Tester


@dataclass
class Hypothesis:
    """单条假设 + 对应 DSL 表达式。"""

    hypothesis: str
    dsl_expr: str
    rationale: str = ""


@dataclass
class RoundResult:
    """一轮 5 角色闭环的产物。"""

    round: int
    hypothesis: Hypothesis | None = None
    factor_values: object = None  # Composer 求值结果（pd.Series）
    test_result: TestResult | None = None
    judge_decision: str = ""  # 'accept' | 'archive' | 'iterate'
    next_direction: str = ""  # Iterator 下一轮方向建议


# ---------------------------------------------------------------------------
# Hypothesizer：LLM 产假设 + DSL
# ---------------------------------------------------------------------------
class Hypothesizer:
    """调用 LLM 产出 1 条假设 + DSL 表达式。"""

    def __init__(self, llm: LLMClient, sandbox: Sandbox | None = None):
        self.llm = llm
        self.sandbox = sandbox or Sandbox()

    def generate(self, topic: str, round_idx: int, feedback: str = "") -> Hypothesis:
        """复用 M3 hypothesis_prompt 模式：逐轮产 1 条。feedback 作为上轮提示。"""
        messages = hypothesis_prompt(
            topic=topic,
            factors_known=[],
            available_operators=sorted(self.sandbox.ALLOWED),
            available_fields=[],  # 上层在闭包内补充；此处仅结构契约
            round_idx=round_idx,
            budget=1,
        )
        # 若有反馈，附在 user 末尾（不破坏 prompt 模板结构）
        if feedback:
            messages = [dict(m) for m in messages]
            messages[-1]["content"] = messages[-1]["content"] + f"\n上一轮反馈：{feedback}"
        item = self.llm.complete_json(messages)
        return Hypothesis(
            hypothesis=str(item.get("hypothesis", "")).strip(),
            dsl_expr=str(item.get("dsl_expr", "")).strip(),
            rationale=str(item.get("rationale", "")).strip(),
        )


# ---------------------------------------------------------------------------
# Composer：Sandbox + 解释器求值
# ---------------------------------------------------------------------------
class Composer:
    """对合法 DSL 调 evaluate 求因子 Series；非法返回 None。"""

    def __init__(self, sandbox: Sandbox | None = None):
        self.sandbox = sandbox or Sandbox()

    def compose(self, hyp: Hypothesis, panel: pd.DataFrame) -> pd.Series | None:
        """Sandbox.validate 先行；不过或求值异常 → None（不抛，交上层裁决）。"""
        if not self.sandbox.validate(hyp.dsl_expr):
            return None
        try:
            return evaluate(hyp.dsl_expr, panel)
        except (DslError, KeyError, ValueError):
            return None


# ---------------------------------------------------------------------------
# TesterRole：复用 M3 Tester
# ---------------------------------------------------------------------------
class TesterRole:
    """薄封装 M3 Tester，承接 Composer 的因子值。"""

    def __init__(self, tester: Tester | None = None):
        self.tester = tester or Tester()

    def test(self, factor_values: object, returns_panel: pd.DataFrame, **kw) -> TestResult:
        """factor_values：长格式 panel（trade_date/symbol/value）。

        kw 透传 Tester.test（p_value / hypothesis_budget / known_factor_panels 等）。
        """
        return self.tester.test(factor_values, returns_panel, **kw)


# ---------------------------------------------------------------------------
# Judge：三决策
# ---------------------------------------------------------------------------
class Judge:
    """依据 TestResult 决策：入库 / 归档 / 迭代。"""

    ARCHIVE_IC_THRESHOLD: float = 0.01  # ic 绝对值低于此值视为彻底弱

    def decide(self, test_result: TestResult) -> str:
        """passed→accept；ic<0.01→archive；否则 iterate。"""
        if test_result.passed:
            return "accept"
        if abs(test_result.ic) < self.ARCHIVE_IC_THRESHOLD:
            return "archive"
        return "iterate"


# ---------------------------------------------------------------------------
# Iterator：下一轮方向
# ---------------------------------------------------------------------------
class Iterator:
    """基于上轮 Judge 决策给下一轮方向建议。"""

    _DIRECTION: dict[str, str] = {
        "accept": "explore_variants",
        "archive": "change_direction",
        "iterate": "refine_params",
    }

    def next_direction(self, round_result: RoundResult, history: list) -> str:
        """history 预留用于后续复杂策略；当前简化为按决策查表。"""
        return self._DIRECTION.get(round_result.judge_decision, "change_direction")
