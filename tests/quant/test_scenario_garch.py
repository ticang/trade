"""GarchForecaster 测试（M5a §4.8.2 情景引擎 Task 1）。

合成 GARCH 数据校验波动聚集建模：fit/forecast/residuals/Ljung-Box。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.scenario.garch import GarchForecaster


def _garch_returns(n: int = 300, seed: int = 0) -> pd.Series:
    """构造波动聚集序列：omega=0.05, alpha=0.05, beta=0.9, t(5)。"""
    rng = np.random.default_rng(seed)
    sig = np.zeros(n)
    sig[0] = 0.2
    for i in range(1, n):
        sig[i] = np.sqrt(0.05 + 0.9 * sig[i - 1] ** 2 + 0.05 * 0.04)
    return pd.Series(rng.standard_t(5, n) * sig)


def _ar_series(n: int = 300, seed: int = 1) -> np.ndarray:
    """构造强自相关序列（Ljung-Box 应拒绝白噪声）。"""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.6 * x[i - 1] + rng.standard_normal()
    return x


def test_arch_installed():
    """arch 包可导入。"""
    import arch  # noqa: F401

    assert arch.__version__


def test_fit_and_forecast():
    """fit 后 forecast_next 返回 (mu, sigma)，sigma>0。"""
    r = _garch_returns(300)
    f = GarchForecaster()
    f.fit(r)
    mu, sigma = f.forecast_next()
    assert sigma > 0
    assert np.isfinite(mu)
    assert np.isfinite(sigma)


def test_sigma_positive():
    """多组数据下 sigma 恒为正。"""
    for seed in range(5):
        r = _garch_returns(300, seed=seed)
        f = GarchForecaster()
        f.fit(r)
        _, sigma = f.forecast_next()
        assert sigma > 0, f"seed={seed} sigma={sigma}"


def test_residuals_returned():
    """residuals 长度等于输入长度。"""
    r = _garch_returns(300)
    f = GarchForecaster()
    f.fit(r)
    resid = f.residuals()
    assert len(resid) == len(r)


def test_ljung_box_pvalue():
    """白噪声 Ljung-Box p>0.05；强自相关 p<0.05。"""
    rng = np.random.default_rng(123)
    white = rng.standard_normal(200)
    ar = _ar_series(300)

    p_white = GarchForecaster.ljung_box_for(white)
    p_ar = GarchForecaster.ljung_box_for(ar)
    assert p_white > 0.05
    assert p_ar < 0.05


def test_forecast_scale_restored():
    """乘 100 拟合后 sigma 还原到原始比例（非 100x）。

    合成数据 std 量级 ~0.1-0.5；若未还原则 sigma 会 >10。
    """
    r = _garch_returns(300, seed=7)
    f = GarchForecaster()
    f.fit(r)
    _, sigma = f.forecast_next()
    emp_std = float(r.std())
    assert sigma < 5 * emp_std, f"sigma={sigma} emp_std={emp_std}（疑似未还原比例）"
    assert sigma > 0
