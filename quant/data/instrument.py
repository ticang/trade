"""Instrument 模型：证券基础信息 + ST 时变状态（设计 v0.5 §4.1.3）。

ST/退市/品种是基础数据（非 symbol 前缀可推断）。ST 是**时变状态**：
同一股票可能在某段时期 ST/*ST/退市，过后恢复，故用 StPeriod 时段序列建模，
而非单一布尔标记。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class StPeriod:
    """ST 状态时段（时变）。

    start<=on<end 视为该时段处于 ST（右开区间）。
    end=None 表示至今仍 ST（视为 +∞）。
    """

    symbol: str
    start: date
    end: date | None
    kind: str = "ST"  # 'ST' | '*ST' | '退市'


@dataclass
class Instrument:
    """证券基础信息（含 ST 时变状态）。

    与 quant.data.models.Instrument（DuckDB schema 载体）不同：
    本类追加 st_periods / etf_crossborder 等基础数据字段，
    服务于 rules_for 的精分类与回测/实盘路由。
    """

    symbol: str
    market: str
    board: str
    product_type: str
    list_date: date | None = None
    delist_date: date | None = None
    status: str = "active"  # 'active' | 'suspended' | 'delisted'
    st_periods: list[StPeriod] = field(default_factory=list)
    etf_crossborder: bool = False  # 跨境 ETF 标记

    def is_st(self, on: date) -> bool:
        """on 时刻是否处于任意 ST 时段。

        命中条件：start <= on < (end or +∞)。
        任一时段命中即返回 True。
        """
        for p in self.st_periods:
            if p.start <= on and (p.end is None or on < p.end):
                return True
        return False
