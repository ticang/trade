"""GARCH-t 波动预测（设计 v0.5 §4.8.2 情景引擎）。

逐 symbol 波动聚集 + 肥尾建模：arch.arch_model 以 Student-t 分布拟合 GARCH(1,1)，
输出次日条件均值 mu 与条件波动 sigma，并提供标准化残差与 Ljung-Box 白噪声检验。

比例缩放：arch 对输入量级敏感，日收益率 ~1e-3 时数值条件差；统一乘 100 后拟合，
forecast 的 sigma 同步除以 100 还原到原始比例（mu 同理）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from arch import arch_model
from arch.univariate.base import ARCHModelResult
from statsmodels.stats.diagnostic import acorr_ljungbox

# arch 对输入量级敏感的缩放因子；forecast 同步还原
_SCALE = 100.0


class GarchForecaster:
    """逐 symbol GARCH-t 波动预测。"""

    def __init__(
        self,
        mean: str = "Zero",
        vol: str = "Garch",
        p: int = 1,
        q: int = 1,
        dist: str = "t",
    ) -> None:
        self._mean = mean
        self._vol = vol
        self._p = p
        self._q = q
        self._dist = dist
        self._fitted: ARCHModelResult | None = None

    def fit(self, returns: pd.Series) -> None:
        """拟合 GARCH-t：乘 100 稳定数值，存 fitted 结果。"""
        scaled = returns.astype(float) * _SCALE
        model = arch_model(
            scaled,
            mean=self._mean,
            vol=self._vol,
            p=self._p,
            q=self._q,
            dist=self._dist,
        )
        self._fitted = model.fit(disp="off")

    def forecast_next(self) -> tuple[float, float]:
        """返回 (mu, sigma)：次日条件均值与波动（还原到原始比例）。"""
        if self._fitted is None:
            raise RuntimeError("先调用 fit()")
        fc = self._fitted.forecast(horizon=1, reindex=False)
        mu_scaled = float(fc.mean.iloc[0, 0])
        sigma_scaled = float(np.sqrt(fc.variance.iloc[0, 0]))
        return mu_scaled / _SCALE, sigma_scaled / _SCALE

    def residuals(self) -> np.ndarray:
        """标准化残差（用于 DCC / 白噪声检查）。"""
        if self._fitted is None:
            raise RuntimeError("先调用 fit()")
        return np.asarray(self._fitted.std_resid)

    @staticmethod
    def ljung_box_for(x: np.ndarray, lags: int = 10) -> float:
        """对序列 x 做 Ljung-Box 检验，返回 p 值（p>0.05 视为白噪声）。"""
        lb = acorr_ljungbox(np.asarray(x, dtype=float), lags=[lags], return_df=True)
        return float(lb["lb_pvalue"].iloc[0])
