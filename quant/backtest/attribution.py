"""绩效归因：正交化回归归因 + Shapley 占位（设计 v0.5 §4.7.4）。

基准可配置。多策略相关因子用回归归因（OLS 含截距），避免共线下顺序 Brinson 病态。
- regression_attribution：excess ~ factor_returns 的 OLS，系数=各因子每期贡献，
  截距=alpha（残差）。贡献年化 = coef * factor.mean() * 252；alpha 年化 = intercept*252。
  正交化回归：因共线时 np.linalg.lstsq 给最小范数解，残差（投影）唯一，r² 与解释力稳健，
  归因结果不因因子顺序而病态。
- shapley_attribution：M1 简化——对 ≤3 因子做精确 Shapley（全子集 R² 边际贡献均分），
  >3 因子降级提示用 regression_attribution（完整实现留 M1.5/M2）。

Barra CNE6 简化风格因子起步（YAGNI，M1 不实现完整风格因子库）。
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

ANNUALIZATION = 252


def regression_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
    benchmark_returns: pd.Series | None = None,
) -> dict:
    """正交化回归归因（避免共线 Brinson 病态）。

    - excess = portfolio_returns - benchmark_returns（benchmark None 则 excess=portfolio_returns）
    - 对齐 index，dropna
    - OLS 回归 excess ~ factor_returns（含截距），系数=各因子贡献（每期），截距=alpha（残差）
    - 逐因子贡献年化：coef * factor_returns.mean() * 252；alpha 年化 = intercept*252
    - factor_returns 列数<1 或样本不足 → contributions 空，alpha/r2=nan
    """
    empty_result: dict = {
        "contributions": pd.Series(dtype=float),
        "alpha_annual": float("nan"),
        "r_squared": float("nan"),
        "residual_annual": float("nan"),
    }

    if factor_returns is None or factor_returns.shape[1] < 1:
        return empty_result

    # 计算超额收益
    if benchmark_returns is None:
        excess = portfolio_returns.copy()
    else:
        excess = portfolio_returns - benchmark_returns

    # 对齐 index 并 dropna
    df = pd.concat(
        [excess.rename("excess"), factor_returns], axis=1
    ).dropna()
    if df.shape[0] < 2:
        # 样本不足（单期或更少）无法拟合
        return empty_result

    factor_cols = list(factor_returns.columns)
    y = df["excess"].to_numpy(dtype=float)
    F = df[factor_cols].to_numpy(dtype=float)
    ones = np.ones((len(df), 1))
    X = np.hstack([F, ones])

    # OLS 最小二乘：共线时 lstsq 给最小范数解，残差（投影）唯一
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat

    # r²
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    factor_coefs = beta[:-1]
    intercept = float(beta[-1])

    # 逐因子贡献年化 = coef * factor.mean() * 252
    factor_means = df[factor_cols].mean()
    contributions = pd.Series(
        factor_coefs * factor_means.to_numpy() * ANNUALIZATION,
        index=factor_cols,
    )
    alpha_annual = intercept * ANNUALIZATION
    # 截距即 alpha（残差项）的贡献：不可由因子解释的常数收益（§4.7.4）
    residual_annual = alpha_annual

    return {
        "contributions": contributions,
        "alpha_annual": alpha_annual,
        "r_squared": r_squared,
        "residual_annual": residual_annual,
    }


def _subset_r_squared(y: np.ndarray, factor_matrix: np.ndarray, cols: tuple[int, ...]) -> float:
    """计算 y 对指定因子子集（含截距）回归的 R²。"""
    if len(cols) == 0:
        # 空子集：仅截距，R²=0
        return 0.0
    X = np.hstack([factor_matrix[:, list(cols)], np.ones((len(y), 1))])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def shapley_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
    benchmark_returns: pd.Series | None = None,
) -> dict:
    """Shapley 归因占位（§4.7.4，M1 简化）。

    M1 实现：对 ≤3 因子做精确 Shapley（全子集 R² 边际贡献均分）；>3 因子时退化
    提示用 regression_attribution（完整实现留 M1.5/M2）。

    - excess = portfolio_returns - benchmark_returns（benchmark None 则 excess=portfolio_returns）
    - 对齐 index，dropna
    - 全子集 R² 边际贡献：Shapley 值 = 因子 i 在所有排列中边际贡献均值
    - 返回 {'contributions': Series(因子->R² 贡献), 'note': str}
    """
    note_degrade = "因子数>3，Shapley 计算量爆炸，降级为回归归因；完整 Shapley 留 M1.5/M2 实现。"

    if factor_returns is None or factor_returns.shape[1] < 1:
        return {"contributions": pd.Series(dtype=float), "note": "无因子输入。"}

    n_factors = factor_returns.shape[1]

    # >3 因子：降级，note 标注，仍返回（回归兜底）
    if n_factors > 3:
        reg = regression_attribution(portfolio_returns, factor_returns, benchmark_returns)
        return {"contributions": reg["contributions"], "note": note_degrade}

    # 计算超额收益
    if benchmark_returns is None:
        excess = portfolio_returns.copy()
    else:
        excess = portfolio_returns - benchmark_returns

    df = pd.concat(
        [excess.rename("excess"), factor_returns], axis=1
    ).dropna()
    if df.shape[0] < 2:
        return {
            "contributions": pd.Series(dtype=float),
            "note": "样本不足，无法计算 Shapley。",
        }

    factor_cols = list(factor_returns.columns)
    y = df["excess"].to_numpy(dtype=float)
    F = df[factor_cols].to_numpy(dtype=float)

    # 精确 Shapley：每个因子在所有子集中的边际 R² 贡献均值
    # Shapley_i = sum over subsets S not containing i:
    #             (|S|! * (n-|S|-1)! / n!) * (R²(S∪{i}) - R²(S))
    n = n_factors
    shapley = np.zeros(n)
    indices = list(range(n))

    for i in indices:
        rest = [j for j in indices if j != i]
        total = 0.0
        # 遍历不含 i 的所有子集 S
        for size in range(0, n):
            # 权重 = |S|! * (n-|S|-1)! / n!
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for subset in itertools.combinations(rest, size):
                r_without = _subset_r_squared(y, F, subset)
                r_with = _subset_r_squared(y, F, subset + (i,))
                total += weight * (r_with - r_without)
        shapley[i] = total

    contributions = pd.Series(shapley, index=factor_cols)
    return {"contributions": contributions, "note": "精确 Shapley（全子集 R² 边际贡献均分）。"}
