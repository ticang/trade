"""主体行为学习标准门禁：复用 M3 Tester，删除"两路共识即入库"（设计 v0.5 §4.9.4）。

入库走标准门禁（样本外 + BH-FDR + 新颖性 + 经济显著 + 人审），
由 M3 Tester 统一裁定；三路（stat/AI/ML）一致性仅作鲁棒性证据，
不提升通过率。原因：三路同源数据非独立样本，共识不代表独立验证。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant.mining.tester import TestResult, Tester


@dataclass
class ActorGateResult:
    """标准门禁结果。"""

    passed: bool                              # M3 Tester 标准门禁裁定
    test_result: TestResult                    # M3 Tester 详细结果
    method_consistency: float                  # 三路一致性（0-1，支持路数/3，鲁棒性证据）
    consistency_as_evidence_only: bool = True  # 一致性非入库依据（§4.9.4）
    human_review_required: bool = True         # 人审必须（§4.9.4 + 人审）
    reasons: list[str] = field(default_factory=list)


class ActorGate:
    """标准门禁：复用 M3 Tester，一致性仅作证据、不门控。"""

    def __init__(self, tester: Tester | None = None):
        self.tester = tester or Tester()

    def test(
        self,
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        *,
        path_supports: list[bool] | None = None,
        industry_panel: pd.DataFrame | None = None,
        mktcap_panel: pd.DataFrame | None = None,
        known_factor_panels: list | None = None,
        hypothesis_budget: int = 10,
        p_value: float | None = None,
    ) -> ActorGateResult:
        """标准门禁测试。

        - 复用 M3 Tester.test 做样本外/BH-FDR/新颖性/经济显著判定。
        - path_supports：三路（stat/AI/ML）是否支持，method_consistency = sum/3。
        - passed 完全由 Tester 定，一致性不参与门控（删除两路共识）。
        - human_review_required 始终 True（人审必须）。
        """
        test_result = self.tester.test(
            factor_panel,
            returns_panel,
            industry_panel=industry_panel,
            mktcap_panel=mktcap_panel,
            known_factor_panels=known_factor_panels,
            hypothesis_budget=hypothesis_budget,
            p_value=p_value,
        )

        # 三路一致性：支持路数 / 3，无 path_supports 信息时默认 0
        if path_supports:
            method_consistency = sum(1 for s in path_supports if s) / 3.0
        else:
            method_consistency = 0.0

        return ActorGateResult(
            passed=test_result.passed,
            test_result=test_result,
            method_consistency=method_consistency,
            reasons=list(test_result.reasons),
        )
