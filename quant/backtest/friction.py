"""交易摩擦模型（设计 v0.5 §4.7.2）。

把一笔订单的成交拆分为：含滑点成交价、佣金、印花税、过户费、滑点成本，
并标注 provisional 费用（无权威来源，回测应用但记 flag；实盘准入由 M0.5
require_verified 在 TradingRuleProvider 层阻断，本模型不阻断）。

费率来源约定：
- 佣金：固定走 FrictionConfig.commission_rate（配置化，§4.7.2）。
- 印花税/过户费：取 rule_json.fees 中对应明细的 value；
  明细缺失或 value 为 None 视为不收取（费率 0，不记 flag）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrictionConfig:
    """摩擦参数。"""

    commission_rate: float = 0.00025  # 佣金 0.025%（双边，配置化）
    slippage_bps: float = 5.0  # 滑点 5bp（简化固定，后续按成交额/波动率建模）


@dataclass
class FillCost:
    """成交成本拆分结果。"""

    fill_price: float  # 含滑点的成交价
    commission: float
    stamp: float  # 印花税（仅卖出）
    transfer: float  # 过户费（双边）
    slippage_cost: float  # 滑点成本（绝对额）
    provisional_flags: list[str] = field(default_factory=list)  # provisional 费用项


class FrictionModel:
    """对单笔订单应用交易摩擦，输出 FillCost。"""

    def __init__(self, config: FrictionConfig | None = None) -> None:
        self.config = config or FrictionConfig()
        # 预计算滑点因子（apply 热路径，避免每次调用重复除法）
        self._slippage_factor = self.config.slippage_bps / 1e4

    def apply(
        self,
        side: str,
        price: float,
        qty: float,
        rule_fees: dict | None = None,
    ) -> FillCost:
        """计算成交成本。

        side ∈ {'buy','sell'}。rule_fees = rule_json['fees']（各项 {value,_confidence}）
        或 None（用 config 默认 / 0）。
        """
        # 滑点：买入成交价上浮、卖出下浮
        sign = 1.0 if side == "buy" else -1.0
        fill_price = price * (1.0 + sign * self._slippage_factor)
        slippage_cost = abs(fill_price - price) * qty

        # 佣金：固定走 config（双边）
        notional = fill_price * qty
        commission = notional * self.config.commission_rate

        # 印花税：仅卖出
        stamp_rate, stamp_prov = _fee_rate(rule_fees, "stamp")
        stamp = notional * stamp_rate if side == "sell" else 0.0

        # 过户费：双边
        transfer_rate, transfer_prov = _fee_rate(rule_fees, "transfer")
        transfer = notional * transfer_rate

        # 收集 provisional flag（仅实际收取且 provisional 的项）
        flags: list[str] = []
        if side == "sell" and stamp > 0.0 and stamp_prov:
            flags.append("stamp")
        if transfer > 0.0 and transfer_prov:
            flags.append("transfer")

        return FillCost(
            fill_price=fill_price,
            commission=commission,
            stamp=stamp,
            transfer=transfer,
            slippage_cost=slippage_cost,
            provisional_flags=flags,
        )


def _fee_rate(rule_fees: dict | None, key: str) -> tuple[float, bool]:
    """从 rule_fees 取某项费率与是否 provisional。

    rule_fees 为 None、缺 key、或 value 为 None → 费率 0、非 provisional（不收取）。
    否则费率 = float(value)，provisional = (_confidence == "provisional")。
    """
    # rule_fees 缺 key、明细非 dict、或 value 为 None → 费率 0、非 provisional（不收取）
    item = (rule_fees or {}).get(key)
    value = item.get("value") if isinstance(item, dict) else None
    if value is None:
        return (0.0, False)
    rate = float(value)
    provisional = item.get("_confidence") == "provisional"
    return (rate, provisional)
