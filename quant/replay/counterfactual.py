"""反事实回放（设计 v0.5 §4.8.1 Task 5）。

基于 event-sourced 历史 bar 重放：改写自身决策观察盈亏差异。

边界声明（§4.8.1）：
- 仅对**自身小单扰动**保证撮合一致性——bar 价格外生不变，撮合仍由 SimBroker
  按 tick / lot / T+N / 量比封顶完成，与实盘撮合规则同构。
- **actor 移除 / 大单移除**需价格冲击模型（Almgren-Chriss 或经验冲击函数）。
  未配置冲击模型时，本引擎仍执行 bar 重放，但把结果标注为 `degraded=True`
  （「相关性叙事」非因果）。调用方据此决定是否纳入归因结论。

复用 M1 的 `SimBroker.match` 逐 bar 撮合；盈亏按 `bar.close` mark-to-market。
"""
from __future__ import annotations

from dataclasses import dataclass

from quant.backtest.sim_broker import Order, SimBroker


@dataclass
class ReplayConfig:
    """反事实回放参数。

    small_order_threshold：单笔成交额占当日成交量比例 < 阈值即视为小单。
        边界含义：小单对 bar 价格无显著冲击，bar 可视作外生。
    require_impact_model_above：超阈值订单需冲击模型，否则降级标注。
    """

    small_order_threshold: float = 0.001
    require_impact_model_above: bool = True


@dataclass
class CounterfactualResult:
    """反事实回放结果。

    pnl_actual：实际决策重放的末日权益（mark-to-close）。
    pnl_counterfactual：改写决策重放的末日权益。
    pnl_diff = pnl_counterfactual - pnl_actual。
    degraded：任一成交为大单（需冲击模型）→ 标注降级（相关性叙事非因果）。
    reason：降级原因（'large_order_requires_impact_model' 或空）。
    """

    pnl_actual: float
    pnl_counterfactual: float
    pnl_diff: float
    degraded: bool = False
    reason: str = ""


class CounterfactualReplay:
    """反事实回放：改写自身小单决策，复现 bar 重放观察盈亏差异。

    复用注入的 SimBroker 逐 bar 撮合（tick / lot / T+N / 量比封顶）。
    盈亏按 `bar.close` mark-to-market。
    """

    def __init__(
        self,
        broker: SimBroker,
        config: ReplayConfig | None = None,
    ) -> None:
        self.broker = broker
        self.config = config or ReplayConfig()

    def classify_order(self, qty: float, bar_volume: float) -> str:
        """按「单笔成交额占当日成交量比例」判定大小单。

        qty / bar_volume < small_order_threshold → 'small'；否则 'large'。
        大单需冲击模型，否则降级（§4.8.1 边界）。
        """
        if bar_volume <= 0:
            return "large"  # 无量即无法撮合，视作需冲击模型外推
        ratio = qty / bar_volume
        return "small" if ratio < self.config.small_order_threshold else "large"

    def replay(
        self,
        history_bars: list,
        actual_trades: list,
        modified_trades: list,
        rule_json: dict,
        initial_cash: float = 1_000_000.0,
    ) -> CounterfactualResult:
        """对 actual_trades 与 modified_trades 分别在 history_bars 上重放。

        trade 为 dict：{"bar_index": int, "order": Order}。
        - 复用 SimBroker.match 逐 bar 撮合，按 bar_index 派发到对应 bar；
          position_qty 跟踪累积持仓（支持 T+N 拒卖）。
        - 末日权益 = cash + Σ持仓按末日 bar.close 的市值（mark-to-market）。
        - 任一成交的 qty/bar.volume ≥ 阈值 → degraded=True，
          reason='large_order_requires_impact_model'，仍执行重放但标注非因果。
        - pnl_diff = pnl_counterfactual - pnl_actual。
        """
        pnl_actual, _ = self._replay_series(
            history_bars, actual_trades, rule_json, initial_cash
        )
        pnl_modified, degraded_modified = self._replay_series(
            history_bars, modified_trades, rule_json, initial_cash
        )

        degraded = degraded_modified
        reason = "large_order_requires_impact_model" if degraded else ""
        return CounterfactualResult(
            pnl_actual=pnl_actual,
            pnl_counterfactual=pnl_modified,
            pnl_diff=pnl_modified - pnl_actual,
            degraded=degraded,
            reason=reason,
        )

    # ------------------------------------------------------------------ 内部
    def _replay_series(
        self,
        history_bars: list,
        trades: list,
        rule_json: dict,
        initial_cash: float,
    ) -> tuple[float, bool]:
        """对单组 trade 序列在 history_bars 上重放，返回（末日权益, 是否降级）。

        逐单派发到对应 bar_index 的 bar，撮合后回写 cash / position；
        末日 mark-to-close 汇总权益。
        """
        cash = float(initial_cash)
        position_qty = 0
        degraded = False

        for trade in trades:
            idx = trade["bar_index"]
            order: Order = trade["order"]
            if idx < 0 or idx >= len(history_bars):
                # 越界：无对应 bar，跳过（与 engine「no_bar」一致语义）
                continue
            bar = history_bars[idx]
            # 大单检测：任一成交为大单即降级
            if self.classify_order(float(order.qty), bar.volume) == "large":
                if self.config.require_impact_model_above:
                    degraded = True
            res = self.broker.match(order, bar, rule_json, position_qty)
            if res.filled and res.cost is not None:
                fill_price = res.cost.fill_price
                fee_total = res.cost.commission + res.cost.stamp + res.cost.transfer
                notional = fill_price * res.fill_qty
                if order.side == "buy":
                    cash -= notional + fee_total
                    position_qty += res.fill_qty
                else:  # sell
                    cash += notional - fee_total
                    position_qty -= res.fill_qty

        # 末日 mark-to-close：用最后一根 bar 的 close 估值
        last_bar = history_bars[-1]
        equity = cash + position_qty * last_bar.close
        return equity, degraded
