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


# ===========================================================================
# Multi-agent orchestrator：5 角色闭环 + 可恢复（§4.3.1 3b + §4.3.2）
# ===========================================================================
from dataclasses import dataclass, field
from typing import Optional

from quant.mining.agent_state import AgentState, AgentStateStore
from quant.mining.tracker import ExperimentTracker


@dataclass
class MultiAgentResult:
    """闭环运行结果：轮次/通过/归档/迭代/恢复点。"""

    run_id: str
    rounds_completed: int
    accepted: list = field(default_factory=list)  # 通过门禁的 Hypothesis
    archived: list = field(default_factory=list)
    iterated: int = 0
    resumed_from: int = 0  # 恢复起始轮（0=全新）


class MultiAgentOrchestrator:
    """驱动 5 角色闭环 max_rounds 轮（或从 resume_from 续）。

    每轮：Hypothesizer.generate → Composer.compose → TesterRole.test →
          Judge.decide → Iterator.next_direction；每轮 checkpoint 落 agent_run。
    accept → accepted.append；archive → archived.append；iterate → iterated+=1。
    可从任意轮 resume 续跑（state_store.resume(run_id) 推断起始轮）。
    """

    def __init__(
        self,
        hypothesizer: Hypothesizer,
        composer: Composer,
        tester_role: "TesterRole",
        judge: "Judge",
        iterator: "Iterator",
        state_store: AgentStateStore,
        tracker: Optional[ExperimentTracker] = None,
    ):
        self.h = hypothesizer
        self.c = composer
        self.t = tester_role
        self.j = judge
        self.it = iterator
        self.state_store = state_store
        self.tracker = tracker

    def run(
        self,
        topic: str,
        panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        *,
        max_rounds: int = 50,
        run_id: Optional[str] = None,
        resume_from: Optional[int] = None,
        hypothesis_budget: int = 50,
        **test_kw,
    ) -> MultiAgentResult:
        """驱动闭环。run_id 确定性 = f"{topic}_{seed}"；resume_from 读 state_store.resume 续轮。"""
        seed = test_kw.pop("seed", 0)
        run_id = run_id or f"{topic}_{seed}"

        # 起始轮：显式传入 > 自动从 checkpoint 推断 > 全新（0）
        # 基于 state.rounds_completed（已完整完成的轮数），而非 round 字段
        # （后者可能在 hypothesize 阶段就写入，不代表该轮已完成）
        if resume_from is None:
            got = self.state_store.resume(run_id)
            if got is not None:
                resume_from = int(got.state.get("rounds_completed", 0))
            else:
                resume_from = 0

        result = MultiAgentResult(run_id=run_id, rounds_completed=resume_from, resumed_from=resume_from)
        history: list = []
        feedback = ""

        for r in range(resume_from, max_rounds):
            round_idx_1b = r + 1  # 1-based 轮次展示
            # phase=hypothesize
            self._checkpoint(run_id, round_idx_1b, "hypothesize", "running", result)
            hyp = self.h.generate(topic, r, feedback)

            # phase=compose
            self._checkpoint(run_id, round_idx_1b, "compose", "running", result)
            factor_series = self.c.compose(hyp, panel)

            # phase=test（Composer 出 None → 构造一个全 fail 的 TestResult）
            self._checkpoint(run_id, round_idx_1b, "test", "running", result)
            if factor_series is None:
                tr = _failed_test_result()
            else:
                factor_long = _to_long_panel(factor_series, panel)
                tr = self.t.test(
                    factor_long,
                    returns_panel,
                    hypothesis_budget=hypothesis_budget,
                    **test_kw,
                )

            # phase=judge
            decision = self.j.decide(tr)

            # phase=iterate
            rr = RoundResult(
                round=round_idx_1b,
                hypothesis=hyp,
                factor_values=factor_series,
                test_result=tr,
                judge_decision=decision,
            )
            feedback = self.it.next_direction(rr, history)
            history.append(rr)

            # 落账
            if decision == "accept":
                result.accepted.append(hyp)
            elif decision == "archive":
                result.archived.append(hyp)
            else:
                result.iterated += 1

            # tracker 每轮一条 experiment（run_id 含轮次避免主键冲突）
            if self.tracker is not None:
                self.tracker.log(
                    run_id=f"{run_id}_r{round_idx_1b}",
                    kind="mining",
                    hypothesis=hyp.hypothesis,
                    expr=hyp.dsl_expr,
                    params={"round": round_idx_1b, "decision": decision},
                    hypothesis_budget=hypothesis_budget,
                    n_tests=1,
                    llm_model=getattr(getattr(self.h, "llm", None), "model", "mock"),
                    seed=seed,
                    snapshot_id="",
                    oos_ic=tr.ic,
                )

            result.rounds_completed = round_idx_1b
            self._checkpoint(run_id, round_idx_1b, "iterate", "running", result)

        # 终态：done
        self._checkpoint(run_id, result.rounds_completed, "iterate", "done", result)
        return result

    def _checkpoint(self, run_id, rnd, phase, status, result):
        """落 agent_run 单行（覆盖式），state 携带当前进度摘要。"""
        self.state_store.checkpoint(
            AgentState(
                run_id=run_id,
                round=rnd,
                phase=phase,
                status=status,
                state={
                    "accepted": len(result.accepted),
                    "archived": len(result.archived),
                    "iterated": result.iterated,
                    "rounds_completed": result.rounds_completed,
                },
            )
        )


def _to_long_panel(factor_series: pd.Series, panel: pd.DataFrame) -> pd.DataFrame:
    """Composer 输出的宽格式 Series（对齐 panel 行）→ Tester 期望的长格式 panel。

    长格式列：trade_date / symbol / value。
    """
    df = panel.assign(value=factor_series.to_numpy())
    return df[["trade_date", "symbol", "value"]]


def _failed_test_result() -> "TestResult":
    """Composer 求值失败时的兜底 TestResult：全门禁不过 → Judge.archive。"""
    return TestResult(
        passed=False,
        ic=0.0,
        ir=0.0,
        bh_fdr_p=1.0,
        novelty_is_novel=True,
        long_short_annual=0.0,
        reasons=["compose_failed"],
    )
