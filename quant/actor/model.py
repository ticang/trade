"""主体行为抽象（设计 v0.5 §4.9.1）。

将市场参与主体建模为带交易历史的实体，用于行为学习。
- 自身（SELF）：QMT 多账户导出，小样本需降级审计
- 游资（HOT_MONEY）：龙虎榜席位，仅上榜股样本，仅适用高波动/高换手子集
- 北向（NORTHBOUND）：沪深股通
- 机构（INSTITUTION）：可扩展

偏差声明（§4.9.2）：每种数据来源都有偏差，默认 bias_note 显式声明。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ActorKind(str, Enum):
    """主体类型。"""

    SELF = "self"
    HOT_MONEY = "hot_money"
    NORTHBOUND = "northbound"
    INSTITUTION = "institution"


# 各 kind 默认偏差声明（§4.9.2）。
# 仅 HOT_MONEY 默认强制带声明（来源偏差最显著，规格明确要求）。
# 其他 kind 仍允许显式传入 bias_note 标注样本偏差。
_DEFAULT_BIAS_NOTE: dict[ActorKind, str] = {
    ActorKind.HOT_MONEY: "仅上榜股样本，仅适用高波动/高换手子集",
}


@dataclass
class ActorTrade:
    """主体单笔成交。"""

    symbol: str
    time: datetime
    side: str  # 'buy' | 'sell'
    price: float
    volume: float
    realized_pnl: float = 0.0
    context: dict = field(default_factory=dict)  # 板块 / 席位 / 其他


@dataclass
class Actor:
    """主体：含交易历史与偏差声明。"""

    id: str
    kind: ActorKind
    trades: list[ActorTrade] = field(default_factory=list)
    # 未显式赋值时取 kind 默认声明（dataclass 用 default_factory 推迟取值）
    bias_note: str = ""

    def __post_init__(self) -> None:
        # 未显式指定 bias_note → 取 kind 默认声明（仅 HOT_MONEY 默认强制）
        if not self.bias_note:
            self.bias_note = _DEFAULT_BIAS_NOTE.get(self.kind, "")

    def add_trade(self, t: ActorTrade) -> None:
        """追加一笔成交。"""
        self.trades.append(t)

    def trades_in(self, start: datetime, end: datetime) -> list[ActorTrade]:
        """闭区间 [start, end] 时间过滤。"""
        return [t for t in self.trades if start <= t.time <= end]
