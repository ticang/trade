"""SimBroker：A 股 bar 级事件驱动撮合（设计 v0.5 §4.7.1/§4.7.3）。

无 L2 盘口，撮合基于当日 bar（开/高/低/收/量）的保守概率模型：
- 限价单：当日是否触及申报价（low<=price<=high），未触及不成交；
  开盘即穿透按 bar.open 成交。成交价标 bar_level_simulated=True。
- 市价单：按 bar.open 成交（次日开盘约定）。
- 一字板封死（开/高/低/收=涨/跌停价）：无法成交。
- 成交量受当日量比封顶（fill_qty <= bar.volume * volume_ratio）。
- T+1：无持仓不允许卖空（A 股无日内回转）。
- 申报合法性：限价单价格须在 tick 网格；买单数量须满足 min_buy 且为
  lot_increment 倍数（卖出允许零股碎单）。

规则由调用方按当日生效版（TradingRuleProvider）取 rule_json 传入。
"""
from __future__ import annotations

from dataclasses import dataclass

from quant.backtest.friction import FillCost, FrictionModel

# tick 网格对齐容差（price/tick 接近整数）
_TICK_TOL = 1e-9


@dataclass
class Order:
    """订单。"""

    symbol: str
    side: str  # 'buy' | 'sell'
    qty: int
    order_type: str = "limit"  # 'limit' | 'market'
    price: float | None = None  # 限价；市价无


@dataclass
class FillResult:
    """撮合结果。"""

    filled: bool
    fill_price: float = 0.0
    fill_qty: int = 0
    cost: FillCost | None = None
    reason: str = ""  # 'ok' / 'limit_unreached' / 'limit_up_sealed' / 'limit_down_sealed' / 'volume_exceeded' / 'no_position_tplusn' / 'illegal_tick' / 'illegal_lot'
    bar_level_simulated: bool = True


@dataclass
class BarSnapshot:
    """当日 bar 简化视图（涨跌停价由调用方据 rule + 前收算）。"""

    open: float
    high: float
    low: float
    close: float
    volume: float
    limit_up: float
    limit_down: float


class SimBroker:
    """A 股 bar 级撮合器。"""

    is_synchronous = True

    def __init__(self, friction: FrictionModel | None = None,
                 volume_ratio: float = 0.1) -> None:
        self.friction = friction or FrictionModel()
        # 当日可成交占比（无 L2 保守估计，§4.7.3）
        self.volume_ratio = volume_ratio

    def match(self, order: Order, bar: BarSnapshot, rule_json: dict,
              position_qty: int = 0) -> FillResult:
        """对单笔订单按当日 bar 撮合。

        步骤：tick 合法 → lot 合法 → 一字板 → 成交判定 → 量比 → T+N → 摩擦。
        """
        tick = rule_json["tick"]
        min_buy = rule_json["min_buy"]
        lot_increment = rule_json["lot_increment"]

        # 1. tick 合法性：限价单申报价须在 tick 网格
        # 浮点取模不可靠（10.0 % 0.01 != 0），用 round(price/tick) 判断整除
        if order.order_type == "limit":
            if order.price is None or abs(order.price / tick - round(order.price / tick)) > _TICK_TOL:
                return FillResult(filled=False, reason="illegal_tick")

        # 2. lot 合法性
        # 买入须满足 min_buy 且为 lot_increment 倍数；
        # 卖出允许零股碎单（持仓本身可能非 lot 倍数），持仓约束归入 T+N 步骤
        if order.side == "buy":
            if order.qty < min_buy or order.qty % lot_increment != 0:
                return FillResult(filled=False, reason="illegal_lot")

        # 3. 一字板封死
        if order.side == "buy" and _sealed_at(bar, bar.limit_up):
            return FillResult(filled=False, reason="limit_up_sealed")
        if order.side == "sell" and _sealed_at(bar, bar.limit_down):
            return FillResult(filled=False, reason="limit_down_sealed")

        # 4. 成交判定（摩擦前成交价 raw_price）
        raw_price = _match_price(order, bar)
        if raw_price is None:
            return FillResult(filled=False, reason="limit_unreached")

        # 5. 量比限制：成交不超当日量比例
        fill_qty = min(order.qty, int(bar.volume * self.volume_ratio))
        if fill_qty < min_buy:
            return FillResult(filled=False, reason="volume_exceeded")

        # 6. T+N：T+1 不允许无持仓卖空（A 股无日内回转）
        # 卖出受持仓封顶：fill_qty 不超 position_qty
        settlement_t = rule_json.get("settlement_T", 0)
        if order.side == "sell":
            if settlement_t >= 1 and position_qty == 0:
                return FillResult(filled=False, reason="no_position_tplusn")
            fill_qty = min(fill_qty, position_qty)

        # 7. 摩擦：fill_price 为摩擦前撮合价，cost.fill_price 含滑点
        cost = self.friction.apply(
            order.side, raw_price, fill_qty, rule_json.get("fees")
        )
        return FillResult(
            filled=True,
            fill_price=raw_price,
            fill_qty=fill_qty,
            cost=cost,
            reason="ok",
        )


def _sealed_at(bar: BarSnapshot, limit_price: float) -> bool:
    """一字板封死：开/高/低/收均等于涨/跌停价。"""
    return (
        bar.open == limit_price
        and bar.high == limit_price
        and bar.low == limit_price
        and bar.close == limit_price
    )


def _match_price(order: Order, bar: BarSnapshot) -> float | None:
    """按订单类型与 bar 区间判定摩擦前成交价；不可成交返回 None。

    市价：bar.open。
    限价买：price<low 未触及；price>high 开盘即穿透按 open；否则按 price。
    限价卖：price>high 未触及；price<low 开盘即穿透按 open；否则按 price。
    """
    if order.order_type == "market":
        return bar.open

    price = order.price  # type: ignore[assignment]
    if order.side == "buy":
        if price < bar.low:
            return None
        if price > bar.high:
            return bar.open  # 开盘即穿透
        return price
    else:  # sell
        if price > bar.high:
            return None
        if price < bar.low:
            return bar.open  # 开盘即穿透
        return price
