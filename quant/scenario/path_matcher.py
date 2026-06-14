"""路径过撮合（设计 v0.5 §4.8.2 情景引擎 Task 4）。

A 股规则在路径评估层生效，而非塞进价格过程：路径收益 → 价格保持连续，
涨跌停截断 / 一字板判定 / T+N 标注在评估时施加。价格过程不破坏，
便于情景生成层（GARCH/DCC/蒙特卡洛）保持统计性质，规则仅在回测/评估端施加。

BarSnapshot 复用 SimBroker 的同名 dataclass，避免并行定义。
"""
from __future__ import annotations

from typing import Literal

import numpy as np

from quant.backtest.sim_broker import BarSnapshot

Side = Literal["buy", "sell"]


def apply_limit_truncation(
    prices: np.ndarray,
    prev_close: float,
    limit_up: float,
    limit_down: float,
) -> np.ndarray:
    """把路径价格截断到 [prev_close*(1-limit_down), prev_close*(1+limit_up)]。

    Args:
        prices: 路径价格序列（连续，未施加规则）。
        prev_close: 前一交易日收盘价（涨跌停基准）。
        limit_up: 涨停比例（如 0.10）。
        limit_down: 跌停比例（如 0.10）。

    Returns:
        截断后价格序列（同 shape，不修改入参）。
    """
    prices = np.asarray(prices, dtype=float)
    upper = prev_close * (1.0 + limit_up)
    lower = prev_close * (1.0 - limit_down)
    return np.clip(prices, lower, upper)


def path_to_bar(path_prices: np.ndarray, prev_close: float) -> list[BarSnapshot]:
    """路径价格序列 → 当日 bar 序列（逐点累积 OHLC）。

    简化：每个时间点的 bar 视为「截止该点的当日累积」——
    open 恒为 prev_close（集合竞价简化），high/low 为路径至此的极值，
    close 为当前点价格。涨跌停价字段以 prev_close 与默认 ±10% 标注（占位，
    精确规则由调用方据 rule_json 重算）。

    Args:
        path_prices: 当日路径价格序列（已是截断后或原始，本函数不做截断）。
        prev_close: 前收（开盘价基准）。

    Returns:
        BarSnapshot 列表，长度 == len(path_prices)。
    """
    prices = np.asarray(path_prices, dtype=float)
    if prices.ndim != 1:
        raise ValueError(f"path_prices 需一维，得到 shape={prices.shape}")

    # 累积极值（向量化 cummax/cummin）
    cum_high = np.maximum.accumulate(prices)
    cum_low = np.minimum.accumulate(prices)

    bars: list[BarSnapshot] = []
    for i in range(prices.shape[0]):
        bars.append(
            BarSnapshot(
                open=prev_close,
                high=float(cum_high[i]),
                low=float(cum_low[i]),
                close=float(prices[i]),
                volume=0.0,  # 路径评估无成交量概念
                limit_up=0.0,
                limit_down=0.0,
            )
        )
    return bars


def match_scenario_path(
    path_returns: np.ndarray,
    prev_close: float,
    rule_json: dict,
    side: Side = "buy",
) -> dict:
    """路径收益 → 价格 → 截断涨跌停 → 评估成交可行性。

    评估层规则（不修改价格过程本身）：
    - 价格 = prev_close*(1+path_returns)，截断到涨跌停区间
    - limit_hit：收盘价==涨停价（买）/跌停价（卖）→ 一字板不可成交
    - feasible_price：截断后收盘价（非一字板时）
    - tplusn_ok：返回 rule 的 settlement_T 值，调用方据持仓判定
    - auction：集合竞价简化——开盘价=prev_close（评估层标注，不强制）

    Args:
        path_returns: 路径收益率序列（如蒙特卡洛采样的当日演化）。
        prev_close: 前收。
        rule_json: 交易规则（含 daily_limit_up/down/settlement_T）。
        side: 'buy' | 'sell'。

    Returns:
        {'feasible_price', 'truncated', 'limit_hit', 'tplusn_ok'}
    """
    returns = np.asarray(path_returns, dtype=float)
    raw_prices = prev_close * (1.0 + returns)

    limit_up = float(rule_json["daily_limit_up"])
    limit_down = float(rule_json["daily_limit_down"])
    truncated_prices = apply_limit_truncation(
        raw_prices, prev_close, limit_up, limit_down
    )
    truncated = bool(not np.allclose(raw_prices, truncated_prices))

    upper = prev_close * (1.0 + limit_up)
    lower = prev_close * (1.0 - limit_down)
    close_price = float(truncated_prices[-1])

    # 一字板判定：收盘价触及封板价即视为不可成交方向
    # （路径评估层简化：以收盘价 == 涨/跌停价 判定，不严格区分开高低收四点相同）
    limit_hit: str | None = None
    feasible_price: float | None = close_price
    if side == "buy" and np.isclose(close_price, upper):
        limit_hit = "limit_up"
        feasible_price = None
    elif side == "sell" and np.isclose(close_price, lower):
        limit_hit = "limit_down"
        feasible_price = None

    tplusn_ok = int(rule_json.get("settlement_T", 0))

    return {
        "feasible_price": feasible_price,
        "truncated": truncated,
        "limit_hit": limit_hit,
        "tplusn_ok": tplusn_ok,
    }


def evaluate_path_pnl(
    path_returns: np.ndarray,
    position: dict,
    prev_close: float,
    rule_json: dict,
) -> float:
    """路径盈亏评估：持仓 × 价格变化（截断后）。

    Args:
        path_returns: 路径收益率序列。
        position: {'qty': int, 'side': 'long'|'short'}。
        prev_close: 前收（基准价）。
        rule_json: 交易规则（用于涨跌停截断）。

    Returns:
        盈亏（正/负 float）。多头：qty*(close-prev_close)；空头反向。
    """
    returns = np.asarray(path_returns, dtype=float)
    raw_prices = prev_close * (1.0 + returns)
    truncated = apply_limit_truncation(
        raw_prices,
        prev_close,
        float(rule_json["daily_limit_up"]),
        float(rule_json["daily_limit_down"]),
    )
    close_price = float(truncated[-1])
    qty = int(position["qty"])
    side = position.get("side", "long")
    if side == "long":
        return qty * (close_price - prev_close)
    # short: 跌价盈利
    return qty * (prev_close - close_price)
