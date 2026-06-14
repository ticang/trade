"""主体行为学习 Task 5 测试：标准门禁复用 M3 Tester（设计 v0.5 §4.9.4）。

覆盖点：
- 强候选（M3 Tester 通过）→ passed=True
- 弱候选（M3 Tester 不过）→ passed=False
- 三路一致性仅为证据、不门控（全支持但候选弱 → passed=False）
- method_consistency = sum(path_supports)/3
- 人审始终必须（即使 passed=True）
- 删除"两路共识即入库"（单路支持+强候选 → passed=True）
- 弱候选 → reasons 含 M3 Tester 的拒因

TDD：本文件先于 quant/actor/gate.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.actor.gate import ActorGate, ActorGateResult
from quant.mining.tester import TestConfig, Tester


# ---------------------------------------------------------------------------
# 合成长格式 panel 辅助（与 test_mining_tester 同构，保证强弱候选可复现）
# ---------------------------------------------------------------------------
RNG = np.random.default_rng(7)
SYMBOLS = [f"S{i:03d}" for i in range(100)]
N_DATES = 20
DATES = pd.date_range("2024-01-01", periods=N_DATES, freq="D").astype("int64") // 10**9


def _panel_from(values_fn, n_dates: int = N_DATES) -> pd.DataFrame:
    """生成长格式 panel：列 trade_date / symbol / value。"""
    rows = []
    for i in range(n_dates):
        vals = values_fn(i)
        for s, v in zip(SYMBOLS, vals):
            rows.append((DATES[i], s, float(v)))
    return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])


def _strong_factor_panel() -> pd.DataFrame:
    """因子截面单调 + 小噪声，IC 高、IR 可解。"""

    def fn(i: int) -> np.ndarray:
        base = np.arange(len(SYMBOLS), dtype=float)
        return base + RNG.normal(0, 0.5, size=len(SYMBOLS))

    return _panel_from(fn)


def _returns_panel_aligned(factor_panel: pd.DataFrame, slope: float = 0.001) -> pd.DataFrame:
    """收益与因子同序：returns = slope*rank(factor) + 噪声。"""

    def fn(i: int) -> np.ndarray:
        f_vals = factor_panel[factor_panel["trade_date"] == DATES[i]]["value"].to_numpy()
        order = np.argsort(f_vals)
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(len(order), dtype=float)
        return slope * ranked + RNG.normal(0, slope * 0.3, size=len(order))

    return _panel_from(fn)


def _random_panel(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _panel_from(lambda i: rng.normal(0, 0.01, size=len(SYMBOLS)))


def _make_tester() -> Tester:
    """复用 M3 Tester，阈值放低 min_long_short_annual 以便强候选稳过。"""
    return Tester(TestConfig(min_long_short_annual=0.0))


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_gate_uses_m3_tester() -> None:
    """强候选 → M3 Tester 通过 → passed=True。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())
    result = gate.test(factor, returns, p_value=0.001, hypothesis_budget=10)
    assert isinstance(result, ActorGateResult)
    assert result.passed is True, f"reasons={result.test_result.reasons}"
    assert result.test_result.passed is True


def test_gate_rejects_weak() -> None:
    """弱候选 → passed=False。"""
    factor = _random_panel(seed=1)
    returns = _random_panel(seed=2)
    gate = ActorGate(_make_tester())
    result = gate.test(factor, returns, p_value=0.5, hypothesis_budget=10)
    assert result.passed is False
    assert result.test_result.passed is False


def test_consistency_is_evidence_not_gate() -> None:
    """三路全支持但候选弱 → passed=False；一致性不门控（§4.9.4）。"""
    factor = _random_panel(seed=3)
    returns = _random_panel(seed=4)
    gate = ActorGate(_make_tester())
    result = gate.test(
        factor, returns, p_value=0.5, hypothesis_budget=10,
        path_supports=[True, True, True],
    )
    assert result.method_consistency == 1.0
    assert result.passed is False
    assert result.consistency_as_evidence_only is True


def test_consistency_computed() -> None:
    """path_supports=[True,True,False] → method_consistency=2/3。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())
    result = gate.test(
        factor, returns, p_value=0.001, hypothesis_budget=10,
        path_supports=[True, True, False],
    )
    assert abs(result.method_consistency - 2.0 / 3.0) < 1e-9


def test_human_review_always_required() -> None:
    """即使 passed=True → human_review_required=True（人审必须）。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())
    result = gate.test(factor, returns, p_value=0.001, hypothesis_budget=10)
    assert result.passed is True
    assert result.human_review_required is True


def test_no_two_path_consensus_logic() -> None:
    """单路支持 + 强候选 → passed=True（删除"两路共识即入库"，§4.9.4）。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())
    result = gate.test(
        factor, returns, p_value=0.001, hypothesis_budget=10,
        path_supports=[True, False, False],
    )
    assert result.method_consistency == 1.0 / 3.0
    # 不要求两路共识：单路支持 + Tester 通过即入库候选
    assert result.passed is True


def test_reasons_collected() -> None:
    """弱候选 → reasons 含 M3 Tester 的拒因。"""
    factor = _random_panel(seed=8)
    returns = _random_panel(seed=9)
    gate = ActorGate(_make_tester())
    result = gate.test(factor, returns, p_value=0.5, hypothesis_budget=50)
    assert result.passed is False
    assert len(result.reasons) >= 1
    # reasons 必含至少一个 M3 Tester 拒因码
    m3_reasons = {"ic_below_min", "ir_below_min", "bh_fdr_fail",
                  "novelty_fail", "long_short_annual_below_min"}
    assert any(r in m3_reasons for r in result.reasons)
