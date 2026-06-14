"""回测引擎事件循环（设计 v0.5 §4.7 / §7.2 / §4.7.6）。

事件驱动遍历交易日：bind panel 到 snapshot → FactorRegistry.compute_panel（PIT 由
FactorContext 强制）→ strategy.on_bar 产单 → SimBroker.match 撮合 → 成交回写
持仓/现金 → 当日权益按 close mark-to-market。

可复现：同 snapshot_id + 同 panel + 同 bars + 同 strategy 二次运行结果一致
（因子 PIT 视图确定，撮合无随机）。PIT：因子计算只通过 FactorContext 访问数据，
未来 available_at 的行不进入当日 factor_panel。

风控（RiskEngine）在 D 阶段做，本引擎不接；on_bar 直接产单撮合。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Callable

import pandas as pd

from quant.backtest.sim_broker import BarSnapshot, FillResult, Order, SimBroker
from quant.factor.registry import FactorRegistry

# rule_json 按当日生效版由调用方提供（M1 简化为固定或 lambda）
RuleJsonFn = Callable[[str, date], dict]


@dataclass
class Position:
    """持仓：数量与平均成本。"""

    qty: int = 0
    avg_cost: float = 0.0


class BacktestStrategy:
    """最小策略 Protocol（M1.5 完整 Strategy 引擎的前身）。子类实现 on_bar。

    on_bar 据当日因子面板 + 持仓 + 现金产订单；返回 list[Order]。
    required_factors 声明依赖的因子名，engine 据此装配 factor_panel。
    """

    required_factors: list[str] = []

    def on_bar(
        self,
        date: date,
        factor_panel: pd.DataFrame,
        positions: dict[str, Position],
        cash: float,
        bars_today: dict[str, BarSnapshot],
    ) -> list[Order]:
        raise NotImplementedError


@dataclass
class BacktestResult:
    """回测结果：权益曲线、成交明细、末日持仓、是否含回填段 PIT。"""

    equity_curve: pd.Series  # index=date，value=总权益（现金 + 持仓市值）
    fills: list = field(default_factory=list)
    final_positions: dict = field(default_factory=dict)
    # 是否含回填段 PIT（E 集成时由数据层打标，C3 默认 False）
    backtest_on_inferred_pit: bool = False


class BacktestEngine:
    """事件驱动回测引擎。

    逐交易日：PIT 装配 factor_panel → on_bar → match → 回写持仓/现金 →
    按当日 close mark-to-market 权益。
    """

    def __init__(
        self,
        registry: FactorRegistry,
        broker: SimBroker | None = None,
        initial_cash: float = 1_000_000.0,
    ) -> None:
        self.registry = registry
        self.broker = broker or SimBroker()
        self.initial_cash = initial_cash

    def run(
        self,
        panel: pd.DataFrame,
        bars: dict,
        trading_days: list,
        strategy: BacktestStrategy,
        rule_json_fn: RuleJsonFn,
        snapshot_id: str = "snap_test",
    ) -> BacktestResult:
        """执行事件循环，返回 BacktestResult。

        - panel：长格式（symbol/trade_date/available_at + 字段），PIT 由 FactorContext 强制
        - bars：{(symbol, date): BarSnapshot}
        - trading_days：排序的 date 列表
        - rule_json_fn(symbol, date) -> dict：当日生效规则
        - snapshot_id：绑定因子快照（可复现性）
        """
        cash = float(self.initial_cash)
        positions: dict[str, Position] = {}
        fills: list[dict] = []
        equity: dict[date, float] = {}

        universe = sorted(panel["symbol"].unique().tolist()) if not panel.empty else []

        for day in trading_days:
            # 1. 装配 PIT 安全 factor_panel：decision_time = 当日 16:00（收盘后）
            decision_time = datetime.combine(day, time(hour=16, minute=0))
            factor_panel = self.registry.compute_panel(
                names=strategy.required_factors,
                t=decision_time,
                universe=universe,
                snapshot_id=snapshot_id,
                panel=panel,
            )

            # 2. 当日 bars（策略可能用于参考；撮合用 bars[(symbol, day)]）
            bars_today = {s: bars[(s, day)] for s in universe if (s, day) in bars}

            # 3. 策略产单
            orders = strategy.on_bar(day, factor_panel, positions, cash, bars_today)

            # 4. 逐单撮合 → 回写持仓/现金
            for order in orders:
                key = (order.symbol, day)
                bar = bars.get(key)
                if bar is None:
                    # 无当日 bar：跳过（记录未成交）
                    fills.append(_fill_record(day, order, FillResult(filled=False, reason="no_bar")))
                    continue
                rule = rule_json_fn(order.symbol, day)
                pos_qty = positions.get(order.symbol, Position()).qty
                res = self.broker.match(order, bar, rule, pos_qty)
                if res.filled:
                    cash = _apply_fill(cash, positions, order, res, day)
                fills.append(_fill_record(day, order, res))

            # 5. 当日权益：cash + Σ 持仓按当日 close 市值（mark-to-market）
            mkt = sum(
                p.qty * bars[(s, day)].close
                for s, p in positions.items()
                if p.qty != 0 and (s, day) in bars
            )
            equity[day] = cash + mkt

        equity_curve = pd.Series(equity, name="equity")
        equity_curve.index.name = "date"
        return BacktestResult(
            equity_curve=equity_curve,
            fills=fills,
            final_positions=positions,
        )


def _apply_fill(
    cash: float,
    positions: dict[str, Position],
    order: Order,
    res: FillResult,
    day: date,
) -> float:
    """成交回写：更新现金与持仓（买入加权平均成本，卖出减仓），返回新现金。

    成交总现金流出 = 含滑点成交价 * qty + 佣金 + 印花税 + 过户费
    （slippage 已含在 fill_price 内，不重复计入）。
    """
    assert res.cost is not None  # 成交必有 cost
    fill_price = res.cost.fill_price
    qty = res.fill_qty
    fee_total = res.cost.commission + res.cost.stamp + res.cost.transfer
    notional = fill_price * qty

    pos = positions.setdefault(order.symbol, Position())
    if order.side == "buy":
        # 买入：扣总成本（notional + 费）；加权平均成本
        cash -= notional + fee_total
        new_qty = pos.qty + qty
        if new_qty > 0:
            pos.avg_cost = (pos.avg_cost * pos.qty + fill_price * qty) / new_qty
        pos.qty = new_qty
    else:  # sell
        # 卖出：收入 notional，扣费；avg_cost 不变（卖出不影响余股成本）
        cash += notional - fee_total
        pos.qty -= qty
    return cash


def _fill_record(day: date, order: Order, res: FillResult) -> dict:
    """成交明细记录（供结果回放与 mark-to-market 验证）。"""
    cost_total = 0.0
    if res.filled and res.cost is not None:
        cost_total = res.cost.fill_price * res.fill_qty + (
            res.cost.commission + res.cost.stamp + res.cost.transfer
        )
    return {
        "date": day,
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "order_qty": order.qty,
        "filled": res.filled,
        "fill_qty": res.fill_qty,
        "fill_price": res.fill_price,
        "cost_total": cost_total,
        "reason": res.reason,
    }
