"""单 agent 假设挖掘闭环（设计 v0.5 §4.3.1 3a + §4.3.2）。

循环 hypothesis_budget 次：
1. LLM 产假设 + DSL 表达式
2. Sandbox 校验算子白名单（不合法跳过）
3. 解释器求值因子 Series（异常跳过）
4. 由 IC 序列的 Newey-West t 近似 p_value，喂 Tester 五门
5. tracker 落库；通过门禁入候选库，否则归档拒因

run_id 确定性 f"{topic}_{seed}_{budget}"，多次 run 互不冲突。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from scipy.stats import norm

from quant.data.sqlite_store import SqliteStore
from quant.dsl.interpreter import DslError, evaluate
from quant.dsl.sandbox import Sandbox
from quant.factor.eval import information_ratio, rank_ic_series
from quant.llm.client import LLMClient
from quant.llm.prompt import hypothesis_prompt
from quant.mining.tester import Tester
from quant.mining.tracker import ExperimentTracker


@dataclass
class MineResult:
    """单轮挖掘结果。"""

    run_id: str
    n_hypotheses: int
    n_passed: int
    candidates: list[dict] = field(default_factory=list)  # 通过门禁：{hypothesis, expr, test_result}
    failures: list[dict] = field(default_factory=list)  # 拒因：{hypothesis, expr, reason}


class SingleAgentMine:
    """单 agent 闭环：LLM → DSL → Tester → 入库。"""

    def __init__(
        self,
        llm: LLMClient,
        tester: Tester,
        tracker: ExperimentTracker,
        store: SqliteStore | None = None,
        sandbox: Sandbox | None = None,
    ):
        self.llm = llm
        self.tester = tester
        self.tracker = tracker
        self.store = store
        self.sandbox = sandbox or Sandbox()

    def run(
        self,
        topic: str,
        panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        *,
        hypothesis_budget: int = 10,
        seed: int = 0,
        industry_panel: pd.DataFrame | None = None,
        mktcap_panel: pd.DataFrame | None = None,
        known_factor_panels: list | None = None,
        snapshot_id: str = "snap_m3",
        known_factors: list[str] | None = None,
    ) -> MineResult:
        """跑 hypothesis_budget 轮假设挖掘，返回 MineResult。"""
        run_id = f"{topic}_{seed}_{hypothesis_budget}"
        candidates: list[dict] = []
        failures: list[dict] = []
        known = known_factors or []
        messages = hypothesis_prompt(topic, known, hypothesis_budget)

        for i in range(hypothesis_budget):
            # LLM 输出不可解析（非对象 / JSON 数组 / 空内容）→ 记 failure，不崩
            try:
                item = self.llm.complete_json(messages)
            except (ValueError, TypeError):
                failure = {"hypothesis": "", "expr": "", "params": {}, "reason": "llm_parse_error"}
                failures.append(failure)
                self._log(run_id, i, "", "", {}, hypothesis_budget, seed, snapshot_id, None)
                continue

            hypothesis = str(item.get("hypothesis", "")).strip()
            dsl_expr = str(item.get("dsl_expr", "")).strip()
            params = item.get("params", {}) or {}

            record = {"hypothesis": hypothesis, "expr": dsl_expr, "params": params}

            # 门一：算子白名单
            if not self.sandbox.validate(dsl_expr):
                failures.append({**record, "reason": "dsl_invalid"})
                self._log(run_id, i, hypothesis, dsl_expr, params, hypothesis_budget, seed, snapshot_id, None)
                continue

            # 门二：解释器求值
            try:
                factor_series = evaluate(dsl_expr, panel)
            except (DslError, KeyError, ValueError):
                failures.append({**record, "reason": "dsl_eval_error"})
                self._log(run_id, i, hypothesis, dsl_expr, params, hypothesis_budget, seed, snapshot_id, None)
                continue

            # Series → 长格式 factor_panel（与 panel 行对齐）
            factor_panel = _series_to_long_panel(panel, factor_series)

            # 由 IC 序列的 Newey-West t 近似 p_value（双侧）
            p_value = _ic_p_value(factor_panel, returns_panel, industry_panel, mktcap_panel)

            test_result = self.tester.test(
                factor_panel,
                returns_panel,
                industry_panel=industry_panel,
                mktcap_panel=mktcap_panel,
                known_factor_panels=known_factor_panels,
                hypothesis_budget=hypothesis_budget,
                p_value=p_value,
            )

            oos_ic = test_result.oos_ic if hasattr(test_result, "oos_ic") else test_result.ic
            self._log(run_id, i, hypothesis, dsl_expr, params, hypothesis_budget, seed, snapshot_id, oos_ic)

            if test_result.passed:
                candidates.append({**record, "test_result": test_result})
            else:
                failures.append({**record, "reason": ",".join(test_result.reasons) or "rejected"})

        return MineResult(
            run_id=run_id,
            n_hypotheses=hypothesis_budget,
            n_passed=len(candidates),
            candidates=candidates,
            failures=failures,
        )

    def _log(
        self,
        run_id: str,
        index: int,
        hypothesis: str,
        dsl_expr: str,
        params: dict,
        budget: int,
        seed: int,
        snapshot_id: str,
        oos_ic: float | None,
    ) -> None:
        """落一条实验记录（run_id + 轮次索引，保证多条可区分）。"""
        self.tracker.log(
            run_id=f"{run_id}_{index}",
            kind="mining",
            hypothesis=hypothesis,
            expr=dsl_expr,
            params=params,
            hypothesis_budget=budget,
            n_tests=index + 1,
            llm_model=self.llm.model,
            seed=seed,
            snapshot_id=snapshot_id,
            oos_ic=oos_ic,
        )


def _series_to_long_panel(panel: pd.DataFrame, factor_series: pd.Series) -> pd.DataFrame:
    """因子 Series（与 panel 行对齐）→ 长格式 trade_date/symbol/value。"""
    out = pd.DataFrame(
        {
            "trade_date": panel["trade_date"].to_numpy(),
            "symbol": panel["symbol"].to_numpy(),
            "value": factor_series.to_numpy(),
        }
    )
    return out


def _ic_p_value(
    factor_panel: pd.DataFrame,
    returns_panel: pd.DataFrame,
    industry_panel: pd.DataFrame | None,
    mktcap_panel: pd.DataFrame | None,
) -> float | None:
    """由 IC 序列的 Newey-West t 近似双侧 p；t 不可解 → None。"""
    ic_series = rank_ic_series(factor_panel, returns_panel, industry_panel, mktcap_panel)
    _ir, t = information_ratio(ic_series)
    if t != t:  # NaN
        return None
    return float(2.0 * (1.0 - norm.cdf(abs(t))))
