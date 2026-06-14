"""自身画像降级：行为审计 + 规则化提醒（设计 v0.5 §4.9.5）。

自身（SELF）QMT 数据小样本，统计建模无意义，降级为非建模的审计：
- 追高（chasing_high）：买入价接近当日高点
- 割肉（cutting_loss）：卖出实现亏损低于阈值
- 持仓过久（holding_too_long）：同 symbol buy→sell 间隔过长
- 频繁交易（frequent_trading）：某日成交数过多
- 小样本降级标注（small_sample）

本模块仅产规则提醒，不做建模。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from quant.actor.model import ActorTrade


@dataclass
class Reminder:
    """规则提醒单条。"""

    kind: str  # 'chasing_high'|'cutting_loss'|'holding_too_long'|'frequent_trading'
    symbol: str
    detail: str
    severity: str = "info"  # 'info'|'warn'


@dataclass
class SelfAuditResult:
    """审计结果：提醒列表 + 样本量 + 小样本标注。"""

    reminders: list[Reminder] = field(default_factory=list)
    n_trades: int = 0
    small_sample: bool = False  # 样本量 < 阈值 → 降级标注


class SelfAudit:
    """自身交易审计器：规则提醒（非建模对象）。"""

    def __init__(
        self,
        chase_threshold: float = 0.05,
        loss_cut_threshold: float = -0.08,
        holding_days_too_long: int = 60,
        frequent_trades_per_day: int = 5,
        small_sample_threshold: int = 30,
    ) -> None:
        self.chase_threshold = chase_threshold
        self.loss_cut_threshold = loss_cut_threshold
        self.holding_days_too_long = holding_days_too_long
        self.frequent_trades_per_day = frequent_trades_per_day
        self.small_sample_threshold = small_sample_threshold

    def audit(
        self,
        trades: list[ActorTrade],
        *,
        day_highs: Optional[dict] = None,
    ) -> SelfAuditResult:
        """审计自身交易，产规则提醒（非建模）。

        - chasing_high：buy 且价格接近当日高点
        - cutting_loss：sell 且实现亏损率 < 阈值
        - holding_too_long：同 symbol buy→sell 间隔 > 阈值天数
        - frequent_trading：某日 trades 数 > 阈值
        - small_sample：n_trades < 阈值 → small_sample=True
        """
        reminders: list[Reminder] = []
        day_highs = day_highs or {}

        # buy 价位簿：symbol → 最近一笔 buy（用于割肉成本与持仓间隔判定）
        last_buy: dict[str, ActorTrade] = {}

        for t in trades:
            if t.side == "buy":
                last_buy[t.symbol] = t
                # 追高：买入价接近当日高点
                self._check_chasing_high(t, day_highs, reminders)
            elif t.side == "sell":
                prior_buy = last_buy.get(t.symbol)
                if prior_buy is not None:
                    # 割肉：卖出实现亏损率
                    self._check_cutting_loss(t, prior_buy, reminders)
                    # 持仓过久：buy→sell 间隔
                    self._check_holding_too_long(prior_buy, t, reminders)

        self._check_frequent_trading(trades, reminders)

        n_trades = len(trades)
        return SelfAuditResult(
            reminders=reminders,
            n_trades=n_trades,
            small_sample=n_trades < self.small_sample_threshold,
        )

    # ------------------------------------------------------------------
    # 规则判定
    # ------------------------------------------------------------------

    def _check_chasing_high(
        self,
        t: ActorTrade,
        day_highs: dict,
        reminders: list[Reminder],
    ) -> None:
        """追高：buy 价接近当日高点（距高点 < chase_threshold）。"""
        key = (t.symbol, t.time.date())
        high = day_highs.get(key)
        if high is None or high <= 0:
            return
        gap = (high - t.price) / high
        if gap < self.chase_threshold:
            reminders.append(
                Reminder(
                    kind="chasing_high",
                    symbol=t.symbol,
                    detail=(
                        f"买入价 {t.price:.2f} 接近当日高点 {high:.2f}"
                        f"（距高点 {gap:.1%}）"
                    ),
                    severity="warn",
                )
            )

    def _check_cutting_loss(
        self,
        sell: ActorTrade,
        buy: ActorTrade,
        reminders: list[Reminder],
    ) -> None:
        """割肉：sell 实现亏损率 < loss_cut_threshold。

        亏损率 = realized_pnl / (成本 * 成交量)。
        """
        cost = buy.price * sell.volume
        if cost <= 0:
            return
        pnl_pct = sell.realized_pnl / cost
        if pnl_pct < self.loss_cut_threshold:
            reminders.append(
                Reminder(
                    kind="cutting_loss",
                    symbol=sell.symbol,
                    detail=(
                        f"卖出亏损 {pnl_pct:.1%}（阈值 {self.loss_cut_threshold:.1%}）"
                    ),
                    severity="warn",
                )
            )

    def _check_holding_too_long(
        self,
        buy: ActorTrade,
        sell: ActorTrade,
        reminders: list[Reminder],
    ) -> None:
        """持仓过久：buy→sell 间隔天数 > holding_days_too_long。"""
        delta_days = (sell.time - buy.time).days
        if delta_days > self.holding_days_too_long:
            reminders.append(
                Reminder(
                    kind="holding_too_long",
                    symbol=sell.symbol,
                    detail=f"持仓 {delta_days} 天（阈值 {self.holding_days_too_long} 天）",
                    severity="info",
                )
            )

    def _check_frequent_trading(
        self,
        trades: list[ActorTrade],
        reminders: list[Reminder],
    ) -> None:
        """频繁交易：某日 trades 数 > frequent_trades_per_day。"""
        per_day: dict[date, int] = defaultdict(int)
        per_day_symbols: dict[date, set] = defaultdict(set)
        for t in trades:
            d = t.time.date()
            per_day[d] += 1
            per_day_symbols[d].add(t.symbol)
        for d, cnt in per_day.items():
            if cnt > self.frequent_trades_per_day:
                reminders.append(
                    Reminder(
                        kind="frequent_trading",
                        symbol="*",
                        detail=(
                            f"{d} 成交 {cnt} 笔"
                            f"（阈值 {self.frequent_trades_per_day} 笔/日）"
                        ),
                        severity="warn",
                    )
                )
