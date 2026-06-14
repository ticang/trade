"""绩效归因测试：正交化回归归因 + Shapley 占位（设计 v0.5 §4.7.4）。

覆盖点：
- regression_attribution 还原已知暴露（coef≈真值），贡献之和≈组合超额均值
- 回归截距=alpha（残差），alpha_annual>0
- benchmark 模式：portfolio-benchmark 作 excess 归因
- 共线因子：回归归因不崩溃（r² 高，系数可能不稳）
- shapley 2 因子：精确 Shapley，贡献非负且和≈总（边际贡献均分）
- shapley >3 因子：note 标注降级，仍返回
- 样本不足：单期 → contributions 空 / alpha nan

TDD：本文件先于 attribution.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.backtest.attribution import (
    regression_attribution,
    shapley_attribution,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def synthetic_factors(rng: np.random.Generator) -> tuple[pd.Series, pd.DataFrame, dict[str, float]]:
    """组合收益 = 0.6*factorA + 0.4*factorB（已知暴露），无 alpha。

    返回 portfolio_returns / factor_returns / 真实 coef。
    """
    n = 300
    factor_a = rng.normal(0, 0.01, size=n)
    factor_b = rng.normal(0, 0.01, size=n)
    true_coef = {"factorA": 0.6, "factorB": 0.4}
    portfolio = true_coef["factorA"] * factor_a + true_coef["factorB"] * factor_b
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame(
        {"factorA": factor_a, "factorB": factor_b}, index=dates
    )
    return portfolio_returns, factor_returns, true_coef


# ---------------------------------------------------------------------------
# regression_attribution
# ---------------------------------------------------------------------------


def test_regression_attribution_sums_to_excess(
    synthetic_factors: tuple[pd.Series, pd.DataFrame, dict[str, float]],
) -> None:
    """已知暴露 → 还原 coef；贡献之和≈组合超额均值（r²≈1）。"""
    portfolio_returns, factor_returns, true_coef = synthetic_factors
    result = regression_attribution(portfolio_returns, factor_returns)

    contributions = result["contributions"]
    assert "factorA" in contributions.index
    assert "factorB" in contributions.index
    # coef 还原：贡献年化 = coef * factor.mean() * 252，反推 coef 应≈真值
    fa_mean = factor_returns["factorA"].mean()
    fb_mean = factor_returns["factorB"].mean()
    np.testing.assert_allclose(
        contributions["factorA"] / (fa_mean * 252),
        true_coef["factorA"],
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        contributions["factorB"] / (fb_mean * 252),
        true_coef["factorB"],
        rtol=1e-6,
    )
    # r²≈1（线性可完全解释）
    assert result["r_squared"] > 0.999
    # 贡献年化之和≈组合超额均值年化
    excess_annual = portfolio_returns.mean() * 252
    np.testing.assert_allclose(
        contributions.sum(), excess_annual, rtol=1e-4
    )


def test_regression_alpha_is_residual(rng: np.random.Generator) -> None:
    """加常数 alpha → 回归截距≈alpha，alpha_annual>0。"""
    n = 300
    factor = rng.normal(0, 0.01, size=n)
    alpha_daily = 0.0005  # 约 12.6% 年化
    portfolio = alpha_daily + 0.5 * factor
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame({"factor": factor}, index=dates)

    result = regression_attribution(portfolio_returns, factor_returns)
    np.testing.assert_allclose(result["alpha_annual"], alpha_daily * 252, rtol=1e-4)
    assert result["alpha_annual"] > 0
    # residual_annual 应≈ alpha_annual（alpha 即残差贡献）
    np.testing.assert_allclose(
        result["residual_annual"], result["alpha_annual"], rtol=1e-4
    )


def test_regression_with_benchmark(rng: np.random.Generator) -> None:
    """portfolio-benchmark 作 excess，归因在 excess 上。"""
    n = 300
    factor = rng.normal(0, 0.01, size=n)
    benchmark = rng.normal(0, 0.005, size=n)
    portfolio = 0.7 * factor + benchmark  # 超额 = 0.7*factor
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    benchmark_returns = pd.Series(benchmark, index=dates, name="benchmark")
    factor_returns = pd.DataFrame({"factor": factor}, index=dates)

    result = regression_attribution(portfolio_returns, factor_returns, benchmark_returns)
    contributions = result["contributions"]
    f_mean = factor_returns["factor"].mean()
    np.testing.assert_allclose(
        contributions["factor"] / (f_mean * 252), 0.7, rtol=1e-6
    )
    # r²≈1（excess 完全由 factor 解释）
    assert result["r_squared"] > 0.999


def test_regression_collinear_factors_stable(rng: np.random.Generator) -> None:
    """factorA 与 factorB 高相关（共线）→ 回归归因不崩，r² 高。

    回归归因避免顺序 Brinson 病态：共线时系数可能不稳，但整体解释力（r²）高，
    不崩溃。验证回归归因在共线场景下仍返回有效结果。
    """
    n = 300
    base = rng.normal(0, 0.01, size=n)
    noise = rng.normal(0, 0.0005, size=n)  # 极小噪声制造高相关
    factor_a = base
    factor_b = base + noise  # 与 A 高度相关
    portfolio = 0.5 * factor_a + 0.5 * factor_b
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame(
        {"factorA": factor_a, "factorB": factor_b}, index=dates
    )

    result = regression_attribution(portfolio_returns, factor_returns)
    # 不崩溃：返回结构完整
    assert "contributions" in result
    assert "r_squared" in result
    assert "alpha_annual" in result
    # r² 高（共线因子仍解释组合）
    assert result["r_squared"] > 0.99
    # 贡献之和≈超额均值年化（即使个别 coef 不稳，组合解释仍准）
    excess_annual = portfolio_returns.mean() * 252
    np.testing.assert_allclose(
        result["contributions"].sum(), excess_annual, rtol=1e-3
    )


def test_insufficient_data_nan(rng: np.random.Generator) -> None:
    """单期数据 → contributions 空 / alpha nan。"""
    factor = np.array([0.01])
    portfolio = np.array([0.005])
    dates = pd.DatetimeIndex(["2023-01-02"])
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame({"factor": factor}, index=dates)

    result = regression_attribution(portfolio_returns, factor_returns)
    assert result["contributions"].empty
    assert np.isnan(result["alpha_annual"])
    assert np.isnan(result["r_squared"])
    assert np.isnan(result["residual_annual"])


# ---------------------------------------------------------------------------
# shapley_attribution
# ---------------------------------------------------------------------------


def test_shapley_two_factors(rng: np.random.Generator) -> None:
    """2 因子 Shapley：精确全子集 R² 边际贡献均分，贡献非负且和≈总 R²。

    构造：两独立因子，Shapley 贡献应≈各自单独 R²（独立时边际贡献=自身 R²）。
    """
    n = 500
    # 独立因子
    factor_a = rng.normal(0, 1, size=n)
    factor_b = rng.normal(0, 1, size=n)
    # 组合收益由两因子等贡献驱动
    portfolio = 1.0 * factor_a + 1.0 * factor_b + rng.normal(0, 0.1, size=n)
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame(
        {"factorA": factor_a, "factorB": factor_b}, index=dates
    )

    result = shapley_attribution(portfolio_returns, factor_returns)
    contributions = result["contributions"]
    assert len(contributions) == 2
    # 贡献非负（R² 分解）
    assert (contributions >= 0).all()
    # 独立因子：两因子 Shapley 贡献应近似相等（对称性）
    assert contributions["factorA"] > 0
    assert contributions["factorB"] > 0
    np.testing.assert_allclose(
        contributions["factorA"], contributions["factorB"], rtol=0.1
    )


def test_shapley_many_factors_degrades(rng: np.random.Generator) -> None:
    """>3 因子 → note 标注降级，仍返回（可能空或回归兜底）。"""
    n = 300
    factors = {f"f{i}": rng.normal(0, 0.01, size=n) for i in range(4)}
    portfolio = sum(factors.values())
    dates = pd.bdate_range("2023-01-02", periods=n)
    portfolio_returns = pd.Series(portfolio, index=dates, name="portfolio")
    factor_returns = pd.DataFrame(factors, index=dates)

    result = shapley_attribution(portfolio_returns, factor_returns)
    assert "note" in result
    # note 应标注降级
    assert "降级" in result["note"] or "回归" in result["note"] or "M1.5" in result["note"] or "M2" in result["note"]
    # 仍返回 contributions（即使空或回归兜底）
    assert "contributions" in result
