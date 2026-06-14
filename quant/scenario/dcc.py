"""cDCC-GARCH 动态相关（设计 v0.5 §4.8.2 情景引擎）。

GARCH 标准化残差 → 动态相关演化：危机态下资产收益同涨同跌加强，相关系数趋向 1。
采用 cDCC（correlation DCC）参数化：

    Q_t = (1-α-β)·Q̄ + α·ε_{t-1}·ε'_{t-1} + β·Q_{t-1}
    R_t = diag(Q_t)^-0.5 · Q_t · diag(Q_t)^-0.5

其中 ε_t 为 t 期标准化残差行向量，Q̄ 为残差样本相关矩阵。
次日协方差 Σ_{T+1} = diag(σ_{T+1}) · R_T · diag(σ_{T+1})：T 期已由最后残差 ε_T
驱动的 R_T 即为已知信息下的次日相关前瞻。

M5a 简化：α/β 取固定经验值（典型 0.05 / 0.9），不做极大似然估计；
注释位预留 MLE 扩展接口（似然 = Σ log|R_t| + ε'_t R_t^-1 ε_t）。
"""
from __future__ import annotations

import numpy as np


class DCC:
    """cDCC-GARCH 动态相关。"""

    def __init__(self, alpha: float = 0.05, beta: float = 0.9) -> None:
        if not (0.0 <= alpha and 0.0 <= beta and alpha + beta < 1.0):
            raise ValueError(f"需 0≤α,0≤β,α+β<1，得到 α={alpha} β={beta}")
        self.alpha = alpha
        self.beta = beta
        self._Q_bar: np.ndarray | None = None
        self._R_last: np.ndarray | None = None
        self._R_series: np.ndarray | None = None  # 全样本 R_t 序列，诊断用
        self._n: int = 0

    def fit(self, std_residuals: np.ndarray) -> None:
        """拟合 cDCC：估 Q̄，迭代演化得 R_t 序列，存 R_last。

        Args:
            std_residuals: (T, n_symbols) 标准化残差（来自 GarchForecaster.residuals）。
        """
        eps = np.asarray(std_residuals, dtype=float)
        if eps.ndim != 2:
            raise ValueError(f"std_residuals 需二维，得到 shape={eps.shape}")
        T, n = eps.shape
        if T < 2:
            raise ValueError(f"样本数需≥2，得到 T={T}")

        self._n = n
        # n=1 退化：相关恒为 [[1]]
        if n == 1:
            self._Q_bar = np.array([[1.0]])
            self._R_last = np.array([[1.0]])
            self._R_series = np.tile([[1.0]], (T, 1, 1))
            return

        # Q̄ = 样本相关矩阵
        qbar = np.corrcoef(eps, rowvar=False)
        # 数值兜底：确保正定（极小 jitter 修正负特征值）
        qbar = self._nearest_pd(qbar)

        a, b = self.alpha, self.beta
        persist = 1.0 - a - b

        # 向量化 cDCC 演化：Q_0 = Q̄，逐步迭代
        Q = qbar.copy()
        R_series = np.empty((T, n, n))
        for t in range(T):
            e = eps[t]  # (n,)
            outer = np.outer(e, e)  # ε_{t-1}ε'_{t-1}（此处用 t 期残差更新到 Q_t）
            Q = persist * qbar + a * outer + b * Q
            R_series[t] = self._Q_to_R(Q)

        self._Q_bar = qbar
        self._R_last = R_series[-1]
        self._R_series = R_series

    @staticmethod
    def _Q_to_R(Q: np.ndarray) -> np.ndarray:
        """Q → R：diag(Q)^-0.5 · Q · diag(Q)^-0.5。"""
        d = np.sqrt(np.diag(Q))
        # 防 0 除：n≥2 时对角为方差，恒正
        inv_d = 1.0 / d
        return inv_d[:, None] * Q * inv_d[None, :]

    @staticmethod
    def _nearest_pd(M: np.ndarray) -> np.ndarray:
        """投影到最近正定矩阵：负特征值抬到小正数。"""
        sym = (M + M.T) / 2.0
        eigval, eigvec = np.linalg.eigh(sym)
        floor = max(eigval.max() * 1e-10, 1e-12)
        clamped = np.where(eigval < floor, floor, eigval)
        if np.all(eigval >= floor):
            return sym  # 已正定，原样返回避免改动
        return (eigvec * clamped) @ eigvec.T

    def forecast_corr_next(self) -> np.ndarray:
        """返回次日相关矩阵 R_{T+1}（n×n，正定，对角为 1）。"""
        if self._R_last is None:
            raise RuntimeError("先调用 fit()")
        return self._R_last

    def forecast_cov_next(self, sigmas: np.ndarray) -> np.ndarray:
        """Σ = diag(sigmas) · R · diag(sigmas)。

        Args:
            sigmas: per symbol 次日波动 (n,)。
        """
        if self._R_last is None:
            raise RuntimeError("先调用 fit()")
        s = np.asarray(sigmas, dtype=float).ravel()
        if s.shape[0] != self._n:
            raise ValueError(f"sigmas 长度 {s.shape[0]} 与符号数 {self._n} 不符")
        d = np.diag(s)
        return d @ self._R_last @ d
