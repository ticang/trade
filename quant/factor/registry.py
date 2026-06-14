"""因子协议与因子注册表（设计 v0.5 §4.2.1）。

Factor：因子的结构化契约（Protocol）。因子代码只通过 FactorContext 访问数据，
PIT 由 FactorContext（A1）强制，本模块不重复 PIT 逻辑。

FactorRegistry：按名注册因子，compute_panel 为每个因子装配 FactorContext 并调
compute，汇总成 DataFrame（index=symbol，列=因子名）。
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

from quant.factor.context import FactorContext


class Factor(Protocol):
    """因子协议（§4.2.1）。

    实现者（duck typing）需暴露：
    - name / factor_version / inputs：因子元信息
    - compute(ctx)：返回 pd.Series，index=symbol，值为该 symbol 的因子值

    PIT 约束不在因子自身实现，由传入的 FactorContext 强制（A1）。
    """

    name: str
    factor_version: str
    inputs: list[str]

    def compute(self, ctx: FactorContext) -> pd.Series: ...


class FactorRegistry:
    """因子注册表。按 name 注册/查询因子，并提供批量计算入口 compute_panel。"""

    def __init__(self) -> None:
        self._factors: dict[str, Factor] = {}

    def register(self, factor: Factor) -> None:
        """注册因子。同名覆盖（后者胜出）。"""
        self._factors[factor.name] = factor

    def get(self, name: str) -> Factor:
        """按名取因子；未注册抛 KeyError。"""
        if name not in self._factors:
            raise KeyError(name)
        return self._factors[name]

    def compute_panel(
        self,
        names: list[str],
        t,
        universe: list[str],
        snapshot_id: str,
        panel: pd.DataFrame,
    ) -> pd.DataFrame:
        """对 names 中每个因子计算并汇总。

        装配 FactorContext(t, universe, snapshot_id, panel)，调 factor.compute(ctx)，
        每个 Series（index=symbol）汇总为 DataFrame（index=symbol，列=name）。
        - names 含未注册因子 → KeyError
        - 某因子 compute 抛 LookAheadError 透传（PIT 由 FactorContext 强制，不吞）
        - 不同因子返回的 symbol 集合可能不同（PIT/数据可得性差异），按 symbol 对齐，
          缺失处为 NaN
        """
        factors = [self.get(name) for name in names]  # 未注册 → KeyError

        series_by_name: dict[str, pd.Series] = {}
        for factor in factors:
            # 每个因子独立装配 ctx（PIT/universe/snapshot 一致）
            ctx = FactorContext(
                decision_time=t,
                universe=universe,
                snapshot_id=snapshot_id,
                panel=panel,
            )
            # LookAheadError 由 ctx 在 compute 内部抛出 → 此处透传不捕获
            series_by_name[factor.name] = factor.compute(ctx)

        # 以 symbol 为行、因子名为列对齐；空输入返回空 DataFrame
        if not series_by_name:
            return pd.DataFrame(index=pd.Index([], name="symbol"))
        df = pd.concat(series_by_name, axis=1)
        df.index.name = "symbol"
        return df
