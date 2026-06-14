"""ScenarioGenerator 测试（M5a §4.8.2 情景引擎 Task 3）。

蒙特卡洛 N 路径（多变量 t 肥尾）+ AI 融合（去相关因子信号防双重计数）+ N 收敛校准。
"""
from __future__ import annotations

import numpy as np

from quant.scenario.generator import ScenarioGenerator


def test_sample_t_shape():
    """sample_multivariate_t(mu(3,), cov(3,3), df=5, n=100) 返回 (100, 3)。"""
    rng = np.random.default_rng(0)
    mu = np.zeros(3)
    cov = np.eye(3)
    gen = ScenarioGenerator(rng)
    x = gen.sample_multivariate_t(mu, cov, df=5.0, n=100)
    assert x.shape == (100, 3)
    assert np.isfinite(x).all()


def test_t_fat_tails():
    """t 采样峰度 > 同 mu/cov 的正态采样峰度（肥尾）。

    标准正态超额峰度=0；t(5) 理论超额峰度=6/(df-4)=6。大样本 n=20000 应稳定呈现
    t 峰度明显高于正态。
    """
    rng_t = np.random.default_rng(1)
    rng_n = np.random.default_rng(1)  # 同 seed 控制随机性差异
    mu = np.zeros(2)
    cov = np.eye(2)
    n = 20000

    gen_t = ScenarioGenerator(rng_t)
    x_t = gen_t.sample_multivariate_t(mu, cov, df=5.0, n=n)
    gen_n = ScenarioGenerator(rng_n)
    x_n = gen_n.sample_multivariate_t(mu, cov, df=1e9, n=n)  # df→∞ 退化为正态

    kurt_t = float(np.mean([_excess_kurtosis(x_t[:, j]) for j in range(2)]))
    kurt_n = float(np.mean([_excess_kurtosis(x_n[:, j]) for j in range(2)]))
    assert kurt_t > kurt_n, f"t 峰度 {kurt_t:.3f} 应大于正态 {kurt_n:.3f}"


def test_generate_paths():
    """generate(mu, cov, 500) 返回 (500, len(mu))。"""
    rng = np.random.default_rng(2)
    mu = np.array([0.001, -0.002, 0.0005])
    cov = np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.0225]])
    gen = ScenarioGenerator(rng)
    paths = gen.generate(mu, cov, n_paths=500)
    assert paths.shape == (500, len(mu))
    assert np.isfinite(paths).all()


def test_ai_fusion_adjusts_mu():
    """AI 融合：mu_factor=0, p_up_ml=[0.8,0.5,0.2], kappa=0.1 → mu_adj=[0.03,0,-0.03]。

    generate 的路径均值应反映 mu_adj（中心偏移）。用大样本验证均值近似 mu_adj。
    """
    rng = np.random.default_rng(3)
    mu_factor = np.zeros(3)
    p_up_ml = np.array([0.8, 0.5, 0.2])
    kappa = 0.1
    cov = np.eye(3) * 0.01  # 小方差便于均值检验
    gen = ScenarioGenerator(rng)
    paths = gen.generate(
        mu_factor,
        cov,
        n_paths=20000,
        df=5.0,
        kappa=kappa,
        p_up_ml=p_up_ml,
        mu_factor=mu_factor,
    )
    expected_adj = np.array([0.03, 0.0, -0.03])
    emp_mean = paths.mean(axis=0)
    # t(5) 大样本均值标准误 ~ sqrt(var/n * df/(df-2))；n=20000 下容差 0.01 足够
    assert np.allclose(emp_mean, expected_adj, atol=0.01), (
        f"路径均值 {emp_mean} 偏离 mu_adj {expected_adj}"
    )


def test_quantile_convergence():
    """quantile_convergence 返回 {q: {N: value}} 结构；N=5000 与 N=1000 分位相对差<5%。"""
    rng = np.random.default_rng(4)
    mu = np.zeros(2)
    cov = np.eye(2)
    gen = ScenarioGenerator(rng)
    result = gen.quantile_convergence(
        mu, cov, df=5.0, quantiles=(0.01, 0.05), ns=(100, 500, 1000, 5000)
    )
    # 结构校验
    assert set(result.keys()) == {0.01, 0.05}
    for q in (0.01, 0.05):
        assert set(result[q].keys()) == {100, 500, 1000, 5000}
        # 收敛：N=5000 vs N=1000 相对差<5%
        v_1000 = result[q][1000]
        v_5000 = result[q][5000]
        rel = abs(v_5000 - v_1000) / abs(v_1000)
        assert rel < 0.05, f"q={q} 未收敛: 1000={v_1000:.4f} 5000={v_5000:.4f} rel={rel:.3f}"


def test_seed_reproducible():
    """同 rng seed 两次 generate 完全相等。"""
    mu = np.array([0.001, 0.002])
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])

    gen1 = ScenarioGenerator(np.random.default_rng(42))
    paths1 = gen1.generate(mu, cov, n_paths=500, df=5.0)

    gen2 = ScenarioGenerator(np.random.default_rng(42))
    paths2 = gen2.generate(mu, cov, n_paths=500, df=5.0)

    assert np.array_equal(paths1, paths2)


def _excess_kurtosis(x: np.ndarray) -> float:
    """样本超额峰度（Fisher 形式：峰度-3）。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    m = x.mean()
    s = x.std()
    if s == 0:
        return 0.0
    z = (x - m) / s
    kurt = np.mean(z**4) - 3.0
    # 小样本修正（可选，此处用无偏估计）
    return float(kurt * (n - 1) / ((n - 2) * (n - 3)) * (n + 1) + 3.0 * (n - 1) / ((n - 2) * (n - 3)) - 3.0)
