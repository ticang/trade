"""主体统计画像（设计 v0.5 §4.9.3 路径1）。

从 ActorTrade 列表推导可解释统计画像：
- 胜率（win_rate）
- 盈亏比（profit_loss_ratio）
- 平均持仓周期（avg_holding_bars，天）
- 板块偏好（sector_preference）
- 买卖点特征（buy/sell_point_features，基于可选 forward_returns）

启发式规则画像，作为路径1（可解释统计）输出。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from quant.actor.model import ActorTrade


@dataclass
class StatProfile:
    """主体统计画像（§4.9.3 路径1）。"""

    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_holding_bars: float = 0.0
    sector_preference: dict = field(default_factory=dict)
    buy_point_features: dict = field(default_factory=dict)
    sell_point_features: dict = field(default_factory=dict)
    n_trades: int = 0


def stat_profile(
    trades: list[ActorTrade],
    *,
    forward_returns: dict | None = None,
) -> StatProfile:
    """计算统计画像。

    - win_rate = 盈利平仓笔数 / 平仓笔数（realized_pnl>0 占比）
    - profit_loss_ratio = mean(盈利) / |mean(亏损)|（无亏损→inf，无盈利→0）
    - avg_holding_bars：同 symbol buy 后最近 sell 配对的天数均值
    - sector_preference：context['sector'] 计数（缺失归入 "unknown"）
    - buy/sell_point_features：forward_returns 提供时计算该 side 的均值
    """
    if not trades:
        return StatProfile()

    # 胜率与盈亏比：仅对 realized_pnl != 0 的平仓交易计数
    closed = [t for t in trades if t.realized_pnl != 0.0]
    wins = [t for t in closed if t.realized_pnl > 0]
    losses = [t for t in closed if t.realized_pnl < 0]

    win_rate = len(wins) / len(closed) if closed else 0.0

    if wins and losses:
        mean_win = sum(t.realized_pnl for t in wins) / len(wins)
        mean_loss = abs(sum(t.realized_pnl for t in losses) / len(losses))
        profit_loss_ratio = mean_win / mean_loss if mean_loss > 0 else float("inf")
    elif wins and not losses:
        # 全盈利：无亏损可比较 → inf（数学定义）
        profit_loss_ratio = float("inf")
    else:
        # 无盈利 → 0
        profit_loss_ratio = 0.0

    # 持仓周期：同 symbol，buy 后时间最近的 sell 配对
    holding_days = _pair_holding_days(trades)
    avg_holding_bars = (
        sum(holding_days) / len(holding_days) if holding_days else 0.0
    )

    # 板块偏好：context['sector'] 计数，缺失归 "unknown"
    sector_count: dict[str, int] = defaultdict(int)
    for t in trades:
        sector = t.context.get("sector", "unknown")
        sector_count[sector] += 1

    # 买卖点特征：forward_returns 提供时计算均值
    buy_features: dict = {}
    sell_features: dict = {}
    if forward_returns is not None:
        buy_rets = _collect_forward_returns(trades, "buy", forward_returns)
        sell_rets = _collect_forward_returns(trades, "sell", forward_returns)
        if buy_rets:
            buy_features["mean"] = sum(buy_rets) / len(buy_rets)
        if sell_rets:
            sell_features["mean"] = sum(sell_rets) / len(sell_rets)

    return StatProfile(
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        avg_holding_bars=avg_holding_bars,
        sector_preference=dict(sector_count),
        buy_point_features=buy_features,
        sell_point_features=sell_features,
        n_trades=len(trades),
    )


def _pair_holding_days(trades: list[ActorTrade]) -> list[float]:
    """同 symbol buy→sell 配对，返回持仓天数列表。

    规则：按 time 排序后，每个 buy 匹配其后时间最近的同 symbol sell；
    已匹配的 sell 不复用。无匹配的 buy 跳过。
    """
    by_symbol: dict[str, list[ActorTrade]] = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)

    holding: list[float] = []
    for symbol, sym_trades in by_symbol.items():
        ordered = sorted(sym_trades, key=lambda x: x.time)
        used_sell_idx: set[int] = set()
        for i, t in enumerate(ordered):
            if t.side != "buy":
                continue
            # 在该 buy 之后找最近的未用 sell
            for j in range(i + 1, len(ordered)):
                if j in used_sell_idx:
                    continue
                if ordered[j].side == "sell" and ordered[j].time >= t.time:
                    holding.append((ordered[j].time - t.time).days)
                    used_sell_idx.add(j)
                    break
    return holding


def _collect_forward_returns(
    trades: list[ActorTrade],
    side: str,
    forward_returns: dict,
) -> list[float]:
    """收集指定 side 交易在 forward_returns 中的收益值。

    forward_returns 键为 (symbol, time)。
    """
    result: list[float] = []
    for t in trades:
        if t.side != side:
            continue
        key = (t.symbol, t.time)
        if key in forward_returns:
            result.append(forward_returns[key])
    return result
