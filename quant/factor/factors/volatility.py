"""波动率因子（设计 v0.5 §4.2.2）。

VolatilityFactor(window)：window 日收益率的样本标准差。
数据访问经注入的 FactorContext（PIT 由 ctx 强制），向量化 pandas。
数据不足（历史 < window+1）→ 该 symbol 因子值为 NaN。
"""
from __future__ import annotations

import pandas as pd

from quant.factor.context import FactorContext
from quant.factor.factors.momentum import _close_per_symbol


class VolatilityFactor:
    """N 日收益率波动因子：最近 window 个日收益的样本标准差。"""

    def __init__(self, window: int = 20) -> None:
        self.window = window

    @property
    def name(self) -> str:
        return f"volatility_{self.window}"

    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        """per symbol 计算最近 window 个日收益的 std。返回 index=symbol 的 Series。"""
        df = _close_per_symbol(ctx, "close")
        # per symbol：取末尾 window+1 个 close → window 个收益 → std(ddof=1)
        ret = (
            df.groupby("symbol")["close"]
            .apply(lambda s: s.iloc[-(self.window + 1):].pct_change().iloc[-self.window:].std(ddof=1)
                   if len(s) >= self.window + 1 else float("nan"))
        )
        ret.index.name = "symbol"
        return ret
