"""动量与反转因子（设计 v0.5 §4.2.2）。

- MomentumFactor(window)：N 日收益率 = latest_close / close_{N日前} - 1
- ReversalFactor(window)：短期反转 = -（window 日收益率）

数据访问经注入的 FactorContext（PIT 由 ctx 强制），向量化 pandas。
数据不足（历史 < window+1）→ 该 symbol 因子值为 NaN（pandas 自然行为）。
"""
from __future__ import annotations

import pandas as pd

from quant.factor.context import FactorContext


def _close_per_symbol(ctx: FactorContext, field: str) -> pd.DataFrame:
    """返回 per symbol 按 trade_date 升序的 close 时序视图。

    列：symbol / trade_date / <field>。PIT 过滤由 ctx.field 完成。
    """
    df = ctx.field(field)
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


class MomentumFactor:
    """N 日动量因子：窗口期收益率。"""

    def __init__(self, window: int = 20) -> None:
        self.window = window

    @property
    def name(self) -> str:
        return f"momentum_{self.window}"

    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        """per symbol 计算 window 日收益率。返回 index=symbol 的 Series。"""
        df = _close_per_symbol(ctx, "close")
        # per symbol：末值 / window 日前值 - 1；不足 window+1 个观测 → NaN
        ret = (
            df.groupby("symbol")["close"]
            .apply(lambda s: s.iloc[-1] / s.iloc[-self.window - 1] - 1.0
                   if len(s) >= self.window + 1 else float("nan"))
        )
        ret.index.name = "symbol"
        return ret


class ReversalFactor:
    """短期反转因子：window 日收益率的相反数。"""

    def __init__(self, window: int = 5) -> None:
        self.window = window

    @property
    def name(self) -> str:
        return f"reversal_{self.window}"

    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        """per symbol 计算 -(window 日收益率)。返回 index=symbol 的 Series。"""
        return -MomentumFactor(self.window).compute(ctx)
