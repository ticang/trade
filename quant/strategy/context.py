"""策略上下文：StrategyRunner 在每个 bar/fill 时点装配并下发给策略（§4.4.1）。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from quant.backtest.engine import Position
from quant.backtest.sim_broker import BarSnapshot
from quant.clock import Clock


@dataclass
class BarContext:
    """on_bar 调用上下文：当前 bar、决策时刻、持仓与因子面板。"""

    bar: BarSnapshot
    symbol: str
    decision_time: datetime
    clock: Clock
    account_id: str
    positions: dict[str, Position]  # symbol -> Position
    factor_panel: pd.DataFrame      # 因子面板（index=symbol，列=因子）
    rules: dict                     # 当日 rule_json（涨跌停等规则）
    trace_id: str = ""


@dataclass
class FillContext:
    """on_fill 调用上下文：单笔成交回执与最新持仓快照。"""

    fill: Any                      # FillResult 或 fill dict（symbol/side/price/qty/cost）
    account_id: str
    positions: dict[str, Position]
    decision_time: datetime
    trace_id: str = ""
