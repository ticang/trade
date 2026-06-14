"""VaR/CVaR 与 Kupiec POF 回测（M5a §4.8.2 多情景稳健性）。

损失分位、尾部期望与覆盖率回测，用于评估多情景路径下的下行风险。
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats


def value_at_risk(portfolio_pnl_paths: np.ndarray, alpha: float = 0.95) -> float:
    """VaR：portfolio_pnl_paths 的 alpha 分位损失（正数=损失额）。

    VaR_alpha = -percentile(pnl_paths, (1-alpha)*100)，即 pnl 下 (1-alpha) 分位取负。
    """
    percentile = (1.0 - alpha) * 100.0
    return -float(np.percentile(portfolio_pnl_paths, percentile))


def conditional_var(portfolio_pnl_paths: np.ndarray, alpha: float = 0.95) -> float:
    """CVaR/Expected Shortfall：超过 VaR 的尾部平均损失（正数=损失额）。"""
    var = value_at_risk(portfolio_pnl_paths, alpha=alpha)
    tail_losses = -portfolio_pnl_paths[portfolio_pnl_paths <= -var]
    if tail_losses.size == 0:
        return var
    return float(tail_losses.mean())


def kupiec_pof(exceptions: int, n: int, alpha: float = 0.95) -> tuple[float, float]:
    """Kupiec POF (Proportion of Failures) 检验。

    H0：实际例外率 p_hat = 理论例外率 p = 1-alpha。
    LR = -2*ln[L(p)] + 2*ln[L(p_hat)] ~ Chi2(df=1)。
    p_value>0.05 → 不拒绝（覆盖率达标）。
    """
    p = 1.0 - alpha
    p_hat = exceptions / n

    # H0 下的对数似然：x*log(p) + (n-x)*log(1-p)
    ll_null = 0.0
    if exceptions > 0:
        ll_null += exceptions * math.log(p)
    if (n - exceptions) > 0:
        ll_null += (n - exceptions) * math.log(1.0 - p)

    # 极大对数似然：x*log(p_hat) + (n-x)*log(1-p_hat)，边界 p_hat∈{0,1} 跳过对应项
    ll_alt = 0.0
    if exceptions > 0:
        ll_alt += exceptions * math.log(p_hat)
    if (n - exceptions) > 0:
        ll_alt += (n - exceptions) * math.log(1.0 - p_hat)

    lr_stat = -2.0 * ll_null + 2.0 * ll_alt
    p_value = 1.0 - float(stats.chi2.cdf(lr_stat, df=1))
    return lr_stat, p_value


def var_backtest(
    pnl_history: np.ndarray,
    var_forecasts: np.ndarray,
    alpha: float = 0.95,
) -> dict:
    """VaR 回测：实际盈亏对照预测 VaR，统计例外并做 Kupiec 检验。

    exceptions = sum(pnl_history < -var_forecasts)（实际损失超过预测 VaR 的次数）。
    coverage_ok = p_value > 0.05（不拒绝=覆盖率达标）。
    """
    pnl_history = np.asarray(pnl_history, dtype=float)
    var_forecasts = np.asarray(var_forecasts, dtype=float)
    n = pnl_history.size
    exceptions = int(np.sum(pnl_history < -var_forecasts))
    lr_stat, p_value = kupiec_pof(exceptions, n, alpha=alpha)
    return {
        "exceptions": exceptions,
        "exception_rate": exceptions / n,
        "lr_stat": lr_stat,
        "p_value": p_value,
        "coverage_ok": p_value > 0.05,
    }
