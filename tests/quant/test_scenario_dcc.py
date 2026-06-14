"""DCC 动态相关测试（M5a §4.8.2 情景引擎 Task 2）。

cDCC-GARCH：GARCH 标准化残差 → 相关演化（危机态相关↑）→ 次日相关/协方差。
"""
from __future__ import annotations

import numpy as np

from quant.scenario.dcc import DCC


def _std_residuals_corr(
    n: int = 200, base_corr: np.ndarray | None = None, seed: int = 0
) -> np.ndarray:
    """构造近似标准化（单位方差）残差，承载给定相关结构。

    通过 Cholesky 分解生成相关多元正态，再按列标准化使其方差≈1。
    """
    rng = np.random.default_rng(seed)
    k = base_corr.shape[0]
    L = np.linalg.cholesky(base_corr)
    x = rng.standard_normal((n, k)) @ L.T
    # 列标准化为单位方差（DCC 输入要求标准化残差）
    z = (x - x.mean(axis=0)) / x.std(axis=0, ddof=1)
    return z


def test_fit_returns_corr_matrix():
    """fit + forecast_corr_next 返回 n×n 相关矩阵。"""
    C = np.array([[1.0, 0.5, 0.3], [0.5, 1.0, 0.2], [0.3, 0.2, 1.0]])
    z = _std_residuals_corr(200, C, seed=1)
    m = DCC()
    m.fit(z)
    R = m.forecast_corr_next()
    assert R.shape == (3, 3)
    assert np.isfinite(R).all()


def test_corr_positive_definite():
    """R 正定（特征值>0），对角≈1。"""
    C = np.array([[1.0, 0.4, 0.4], [0.4, 1.0, 0.4], [0.4, 0.4, 1.0]])
    z = _std_residuals_corr(300, C, seed=2)
    m = DCC()
    m.fit(z)
    R = m.forecast_corr_next()
    eigs = np.linalg.eigvalsh((R + R.T) / 2)
    assert (eigs > 0).all(), f"非正定特征值: {eigs}"
    assert np.allclose(np.diag(R), 1.0, atol=1e-8)


def test_corr_matches_data():
    """symbol0/1 高相关(0.8)、0/2 低(0.1) → R[0,1] 高、R[0,2] 低。"""
    C = np.array([[1.0, 0.8, 0.1], [0.8, 1.0, 0.1], [0.1, 0.1, 1.0]])
    z = _std_residuals_corr(400, C, seed=3)
    m = DCC()
    m.fit(z)
    R = m.forecast_corr_next()
    # 高相关应明显高于低相关
    assert R[0, 1] > 0.5, f"R[0,1]={R[0, 1]}"
    assert R[0, 2] < 0.3, f"R[0,2]={R[0, 2]}"
    assert R[0, 1] - R[0, 2] > 0.3
    # 对称
    assert np.allclose(R, R.T, atol=1e-8)


def test_crisis_correlation_up():
    """后段进入危机态（系统性冲击主导、特异性噪声退场）→ R 后段 off-diagonal 增大。

    DCC 相关动态由残差外积 ε_{t-1}ε'_{t-1} 驱动；单纯缩放幅度因 R_t 归一化被抵消。
    真实危机态是同向冲击主导、横截面相关性结构性上升：构造后段由共同大幅因子
    + 小特异性噪声组成，前段则多噪声、相关性低。
    """
    rng = np.random.default_rng(4)
    n_pre, n_post = 150, 150
    n = 3

    # 前段：高特异性噪声 + 弱公共因子 → 低相关
    common_pre = 0.3 * rng.standard_normal(n_pre)
    z_pre = common_pre[:, None] + rng.standard_normal((n_pre, n))
    z_pre = (z_pre - z_pre.mean(0)) / z_pre.std(0, ddof=1)

    # 后段：强公共因子 + 微弱特异性 → 高相关（系统性冲击主导）
    common_post = 5.0 * rng.standard_normal(n_post)
    z_post = common_post[:, None] + 0.1 * rng.standard_normal((n_post, n))
    z_post = (z_post - z_post.mean(0)) / z_post.std(0, ddof=1)

    z = np.vstack([z_pre, z_post])
    m = DCC(alpha=0.1, beta=0.8)
    m.fit(z)
    Rs = m._R_series
    assert Rs.shape == (n_pre + n_post, n, n)
    off_pre = np.abs(Rs[:n_pre].reshape(-1, 9)[:, [1, 2, 5]]).mean()
    off_post = np.abs(Rs[n_pre:].reshape(-1, 9)[:, [1, 2, 5]]).mean()
    assert off_post > off_pre, (
        f"危机后 off-diagonal 未增大: pre={off_pre:.3f} post={off_post:.3f}"
    )


def test_cov_from_corr_sigmas():
    """forecast_cov_next(sigmas) = diag(σ)·R·diag(σ)，对称正定。"""
    C = np.array([[1.0, 0.6, 0.2], [0.6, 1.0, 0.3], [0.2, 0.3, 1.0]])
    z = _std_residuals_corr(300, C, seed=5)
    m = DCC()
    m.fit(z)
    sigmas = np.array([0.02, 0.03, 0.015])
    R = m.forecast_corr_next()
    cov = m.forecast_cov_next(sigmas)
    expected = np.diag(sigmas) @ R @ np.diag(sigmas)
    assert np.allclose(cov, expected, atol=1e-10)
    assert np.allclose(cov, cov.T, atol=1e-10)
    eigs = np.linalg.eigvalsh((cov + cov.T) / 2)
    assert (eigs > 0).all()


def test_single_symbol():
    """n=1 → R=[[1]]，cov=[[σ²]]。"""
    rng = np.random.default_rng(6)
    z = rng.standard_normal((100, 1))
    z = (z - z.mean(axis=0)) / z.std(axis=0, ddof=1)
    m = DCC()
    m.fit(z)
    R = m.forecast_corr_next()
    assert R.shape == (1, 1)
    assert np.allclose(R, [[1.0]])
    sig = np.array([0.02])
    cov = m.forecast_cov_next(sig)
    assert np.allclose(cov, [[0.02**2]])
