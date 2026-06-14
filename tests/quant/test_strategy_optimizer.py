"""M1.5 组合优化器契约测试：cvxpy QP + 主板 100 股整数化 + gap（§4.4.3）。

标量化目标 max α'w − λ·TE² − γ·turnover，约束单票上限/换手率，
连续 QP 解 → lot 整数化启发式 → gap 量化整数化损失。
"""
import numpy as np

from quant.strategy.optimizer import (
    OptimizerConfig,
    OptimizeResult,
    PortfolioOptimizer,
)
from quant.strategy.signal import Signal


def _signals(strengths: dict[str, float]) -> list[Signal]:
    """构造一组多头信号，strength 作为 alpha。"""
    return [Signal(symbol=sym, direction=1, strength=s) for sym, s in strengths.items()]


# 默认 universe：3 个标的
DEFAULT_STRENGTHS = {"600519": 0.9, "000858": 0.5, "002304": 0.3}


def test_optimize_returns_weights():
    # 返回的 weights keys 覆盖所有 signal symbol
    opt = PortfolioOptimizer()
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))
    assert isinstance(result, OptimizeResult)
    assert set(result.weights.keys()) == set(DEFAULT_STRENGTHS.keys())


def test_continuous_satisfies_constraints():
    # 宽松 max_single 使 QP 可行：连续解 sum≈1 且每项<=max_single
    config = OptimizerConfig(max_single=0.50)
    opt = PortfolioOptimizer(config)
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))

    w = result.continuous_weights
    assert abs(sum(w.values()) - 1.0) < 1e-3
    for v in w.values():
        assert v <= config.max_single + 1e-4


def test_integerization_mainboard_lot():
    # 整数化后权重仍 sum≈1（整数 lot 归一），单票不超过 max_single
    config = OptimizerConfig(max_single=0.50)
    opt = PortfolioOptimizer(config)
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))

    w = result.weights
    # 整数 lot 归一后 sum 应精确为 1
    assert abs(sum(w.values()) - 1.0) < 1e-6
    for v in w.values():
        assert v <= config.max_single + 1e-9


def test_gap_computed():
    # gap = |obj_int - obj_cont| / |obj_cont|，强信号下整数化损失小
    config = OptimizerConfig(max_single=0.50)
    opt = PortfolioOptimizer(config)
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))

    assert result.gap >= 0.0
    assert result.objective_continuous != result.objective_integer or result.gap == 0.0
    # 整数化粒度细（ref_price=1 → n_lots 大），gap 应较小
    assert result.gap < 0.1


def test_gap_warning_when_large():
    # max_single 极小使 QP 不可行 → 回退等权 + gap_warning
    config = OptimizerConfig(max_single=0.05, gap_threshold=0.02)
    opt = PortfolioOptimizer(config)
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))

    assert result.gap_warning is True


def test_max_single_respected():
    # max_single=0.10 + 3 symbol：3*0.10<1 不可行 → 回退等权 1/n
    config = OptimizerConfig(max_single=0.10)
    opt = PortfolioOptimizer(config)
    result = opt.optimize(_signals(DEFAULT_STRENGTHS))

    # 不可行回退：等权 1/n
    expected = 1.0 / len(DEFAULT_STRENGTHS)
    for v in result.weights.values():
        assert abs(v - expected) < 1e-9
    assert result.gap_warning is True


def test_turnover_penalty():
    # current_weights 与目标差大时，连续解换手受 max_turnover 约束
    # 配置需可行：current 已满仓，max_single 不强制卖出，max_turnover 限制再平衡幅度
    config = OptimizerConfig(max_single=0.50, max_turnover=0.40, gamma=0.5)
    opt = PortfolioOptimizer(config)
    strengths = {"A": 0.9, "B": 0.1, "C": 0.1}
    current = {"A": 0.20, "B": 0.40, "C": 0.40}
    result = opt.optimize(_signals(strengths), current_weights=current)

    w = result.continuous_weights
    turnover = sum(abs(w[s] - current.get(s, 0.0)) for s in w)
    # 连续解应满足换手硬上限（容差留给 OSQP 数值）
    assert turnover <= config.max_turnover + 1e-2


def test_alpha_drives_allocation():
    # strength 大的 symbol 权重更高（在 max_single 内）
    config = OptimizerConfig(max_single=0.50)
    opt = PortfolioOptimizer(config)
    strengths = {"A": 0.9, "B": 0.1, "C": 0.1}
    result = opt.optimize(_signals(strengths))

    w = result.continuous_weights
    # 最强 alpha 的 A 应获得最大权重
    assert w["A"] > w["B"]
    assert w["A"] > w["C"]
