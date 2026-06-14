"""ScenarioGenerator 蒙特卡洛情景引擎（设计 v0.5 §4.8.2）。

N 路径采样：GARCH/DCC 协方差 → 多变量 t（肥尾）采样。AI 融合去相关：
    μ_adjusted = μ_factor + κ·(p_up_ml − 0.5)
因子 μ 已含方向信息，p_up_ml 提供 ML 看涨概率的增量信号；κ 控制 ML 信号权重，
减 0.5 去均值防双重计数。校准：分位随 N 增大收敛（相邻 N 相对差<5%）。
"""
from __future__ import annotations

import numpy as np


class ScenarioGenerator:
    """蒙特卡洛 N 路径生成 + AI 融合。"""

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self._rng = rng or np.random.default_rng()

    def sample_multivariate_t(
        self, mu: np.ndarray, cov: np.ndarray, df: float, n: int
    ) -> np.ndarray:
        """多变量 t 采样（肥尾）。返回 (n, len(mu))。

        算法：z ~ N(0, cov)，g ~ Chi2(df)/df，x = mu + z / sqrt(g)。
        df→∞ 时 g→1，退化为多元正态。
        """
        mu = np.asarray(mu, dtype=float).ravel()
        cov = np.asarray(cov, dtype=float)
        d = mu.shape[0]
        if cov.shape != (d, d):
            raise ValueError(f"cov shape {cov.shape} 与 mu 长度 {d} 不符")
        if df <= 0:
            raise ValueError(f"df 需>0，得到 {df}")
        if n <= 0:
            raise ValueError(f"n 需>0，得到 {n}")

        # Cholesky 分解协方差（要求正定）；数值兜底抬负特征值到正数
        try:
            L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            sym = (cov + cov.T) / 2.0
            w, V = np.linalg.eigh(sym)
            floor = max(w.max() * 1e-12, 1e-12)
            w = np.where(w < floor, floor, w)
            L = V @ np.diag(np.sqrt(w))

        z = self._rng.standard_normal((n, d)) @ L.T  # (n, d) ~ N(0, cov)

        # 混合变量 g ~ Chi2(df)/df；df 极大时 g→1 退化为正态
        if df > 1e6:
            x = z
        else:
            g = self._rng.chisquare(df, size=n) / df  # (n,)
            x = z / np.sqrt(g)[:, None]

        return mu[None, :] + x

    def generate(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        n_paths: int = 1000,
        df: float = 5.0,
        kappa: float = 0.0,
        p_up_ml: np.ndarray | None = None,
        mu_factor: np.ndarray | None = None,
    ) -> np.ndarray:
        """生成 N 路径。返回 (n_paths, n_symbols)。

        AI 融合：当 p_up_ml 与 mu_factor 均给出时，
            mu_adj = mu_factor + kappa * (p_up_ml - 0.5)
        否则使用传入的 mu。
        """
        mu = np.asarray(mu, dtype=float).ravel()
        if mu_factor is not None and p_up_ml is not None:
            mu_factor = np.asarray(mu_factor, dtype=float).ravel()
            p_up_ml = np.asarray(p_up_ml, dtype=float).ravel()
            if mu_factor.shape != p_up_ml.shape:
                raise ValueError(
                    f"mu_factor {mu_factor.shape} 与 p_up_ml {p_up_ml.shape} 维度不符"
                )
            mu = mu_factor + kappa * (p_up_ml - 0.5)

        return self.sample_multivariate_t(mu, cov, df=df, n=n_paths)

    def quantile_convergence(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        df: float,
        quantiles: tuple[float, ...] = (0.01, 0.05),
        ns: tuple[int, ...] = (100, 500, 1000, 5000),
    ) -> dict[float, dict[int, float]]:
        """校准：对不同 N 算分位，返回 {q: {N: quantile_value}}。

        收敛判据：相邻 N 的分位相对差<5%（调用方或后续断言校验）。
        聚合维度：把多 symbol 路径投影到逐 symbol 后取平均分位，反映整体尾部水平。
        """
        mu = np.asarray(mu, dtype=float).ravel()
        cov = np.asarray(cov, dtype=float)
        result: dict[float, dict[int, float]] = {}
        for q in quantiles:
            result[q] = {}
            for N in ns:
                paths = self.sample_multivariate_t(mu, cov, df=df, n=N)
                # 多 symbol 取逐 symbol 分位后平均（聚合视图）
                per_symbol_q = np.quantile(paths, q, axis=0)
                result[q][N] = float(per_symbol_q.mean())
        return result
