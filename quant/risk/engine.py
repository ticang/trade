"""RiskEngine 基础层（设计 v0.5 §4.5）。

风控基础层是回测撮合一部分：在撮合前对每笔订单做最终合法性校验，
所有规则从 TradingRuleProvider 提供的 rule_json 读取。

校验维度（全档）：
- 申报合法性：tick 网格 / lot 手数
- 流通性过滤：涨跌停封板 / 停牌 / ST / 退市
- 仓位约束：单票仓位上限 / 总仓位上限 / 单笔金额上限
- 持仓级提示：单仓位止损 / 止盈（标记应平仓仓位）

风控对申报做整数化后做最终合法性校验（与 SimBroker 共用 tick 容差 1e-9）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# tick 网格对齐容差（与 SimBroker 一致）
_TICK_TOL = 1e-9


@dataclass
class RiskConfig:
    """风控阈值配置。"""

    max_single_pct: float = 0.10        # 单票仓位上限 10%
    max_total_pct: float = 0.95         # 总仓位上限 95%
    max_order_value: float = 500_000.0  # 单笔金额上限
    stop_loss_pct: float = 0.10         # 单仓位止损 -10%
    take_profit_pct: float = 0.20       # 止盈 +20%
    trailing_pct: float | None = None   # 跟踪止损（None=关）


@dataclass
class RiskViolation:
    """单条风控违例。"""

    order_id: str
    reason: str


@dataclass
class RiskResult:
    """风控汇总结果。"""

    passed: bool
    violations: list[RiskViolation] = field(default_factory=list)


@dataclass
class PositionInfo:
    """持仓信息（供仓位上限与止损止盈计算）。"""

    symbol: str
    qty: int
    avg_cost: float
    last: float


class RiskEngine:
    """A 股风控基础层。"""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def check(
        self,
        orders: list,
        positions: list[PositionInfo],
        total_equity: float,
        rule_json_fn: Callable[[str], dict],
        bars_today: dict,
        flags: dict | None = None,
    ) -> RiskResult:
        """对每笔订单逐一校验，并扫描持仓做止损止盈提示。

        任一校验违例即 append 一条 RiskViolation，订单被拒。
        passed = (无任何违例)。
        """
        violations: list[RiskViolation] = []
        flags = flags or {}

        # 持仓级提示：止损 / 止盈（针对已有持仓，与单笔 order 校验并存）
        for pos in positions:
            oid = f"pos:{pos.symbol}"
            if pos.avg_cost <= 0:
                continue
            ret = pos.last / pos.avg_cost - 1.0
            if ret <= -self.config.stop_loss_pct:
                violations.append(RiskViolation(order_id=oid, reason="stop_loss_triggered"))
            if ret >= self.config.take_profit_pct:
                violations.append(RiskViolation(order_id=oid, reason="take_profit_triggered"))

        # 预算：已有持仓总市值（用于总仓位上限累加）
        held_value = sum(p.qty * p.last for p in positions)

        # 按票累加本批次拟买入名义价值（模拟成交后单票仓位计算）
        buy_added: dict[str, float] = {}

        for order in orders:
            oid = _order_id(order)
            symbol = order.symbol
            rule = rule_json_fn(symbol)
            bar = bars_today.get(symbol)
            order_flags = flags.get(symbol, {})

            # 名义价值：限价单按申报价，市价单按 bar.close
            unit = order.price if order.order_type == "limit" else (bar.close if bar else 0.0)
            notional = unit * order.qty

            # 1. tick 合法性：限价单申报价须在 tick 网格
            if order.order_type == "limit":
                tick = rule["tick"]
                if order.price is None or abs(order.price / tick - round(order.price / tick)) > _TICK_TOL:
                    violations.append(RiskViolation(order_id=oid, reason="illegal_tick"))

            # 2. lot 合法性：买单须满足 min_buy 且为 lot_increment 倍数
            if order.side == "buy":
                min_buy = rule["min_buy"]
                lot_increment = rule["lot_increment"]
                if order.qty < min_buy or order.qty % lot_increment != 0:
                    violations.append(RiskViolation(order_id=oid, reason="illegal_lot"))

            # 3. 流通性过滤：停牌 / ST / 退市
            if order_flags.get("suspended"):
                violations.append(RiskViolation(order_id=oid, reason="suspend_filtered"))
            if order_flags.get("st"):
                violations.append(RiskViolation(order_id=oid, reason="st_filtered"))
            if order_flags.get("delisted"):
                violations.append(RiskViolation(order_id=oid, reason="delist_filtered"))

            # 4. 涨停封板过滤：买 + low==high==limit_up（封涨停买不进）
            if order.side == "buy" and bar is not None and _sealed_at_limit_up(bar):
                violations.append(RiskViolation(order_id=oid, reason="limit_up_filtered"))

            # 5. 单笔金额上限
            if notional > self.config.max_order_value:
                violations.append(RiskViolation(order_id=oid, reason="max_order_value"))

            # 6. 单票仓位上限：买入后单票市值 / 总权益
            if order.side == "buy" and total_equity > 0:
                buy_added[symbol] = buy_added.get(symbol, 0.0) + notional
                cur_value = _position_value(positions, symbol) + buy_added[symbol]
                if cur_value / total_equity > self.config.max_single_pct:
                    violations.append(RiskViolation(order_id=oid, reason="max_single"))

            # 7. 总仓位上限：买入后 Σ持仓 + 本单 / 总权益
            if order.side == "buy" and total_equity > 0:
                total_after = held_value + sum(buy_added.values())
                if total_after / total_equity > self.config.max_total_pct:
                    violations.append(RiskViolation(order_id=oid, reason="max_total"))

        return RiskResult(passed=not violations, violations=violations)


def _order_id(order: object) -> str:
    """取订单 id：有 id 用 id，否则回退 symbol+side。"""
    oid = getattr(order, "id", None) or getattr(order, "order_id", None)
    if oid:
        return str(oid)
    return f"{getattr(order, 'symbol', '?')}:{getattr(order, 'side', '?')}"


def _sealed_at_limit_up(bar: object) -> bool:
    """涨停封板：开/高/低/收均等于涨停价。"""
    return (
        bar.open == bar.limit_up
        and bar.high == bar.limit_up
        and bar.low == bar.limit_up
        and bar.close == bar.limit_up
    )


def _position_value(positions: list[PositionInfo], symbol: str) -> float:
    """取指定 symbol 已有持仓市值。"""
    for p in positions:
        if p.symbol == symbol:
            return p.qty * p.last
    return 0.0
