"""市场宽度因子（设计 v0.5 §4.1.2 一期诚实化）。

一期差异化定位诚实化：交付「因子工程管线 + 市场宽度因子」，
不宣称散户情绪反向。北向资金 / 融资融券数据存在滞后、披露不全与持仓结构性偏差，
不宜作为散户情绪反向因子源（仅作市场宽度观测，注释明示）。

本模块由日行情自算市场宽度，无需外部情绪数据：
- limit_up_down_counts：per trade_date 涨停/跌停家数 + 涨/跌家数
- consecutive_board_height：per symbol 当前连续涨停天数（断板归零）
- seal_rate：触及涨停中收盘仍封的比例（封板率）
- breadth_factor_series：(涨停-跌停)/total 截面时间序列，供回测/因子引擎

涨跌停阈值简化为主板 ±10%（round(prev*(1±pct), 2)）。
忽略板块差异：创业板/科创板 ±20%、ST ±5% 留待 M0.5 规则接入按板块区分。
"""
from __future__ import annotations

import pandas as pd

# 主板简化涨跌停幅度；M0.5 接入板块规则后按 symbol 维度区分
LIMIT_PCT = 0.1


def _limit_up_price(prev_close: float | pd.Series, pct: float = LIMIT_PCT) -> float | pd.Series:
    """涨停价 = round(prev_close * (1+pct), 2)。"""
    return (prev_close * (1.0 + pct)).round(2)


def _limit_down_price(prev_close: float | pd.Series, pct: float = LIMIT_PCT) -> float | pd.Series:
    """跌停价 = round(prev_close * (1-pct), 2)。"""
    return (prev_close * (1.0 - pct)).round(2)


def _attach_limit_prices(bars: pd.DataFrame, prev_close: pd.Series) -> pd.DataFrame:
    """为每行 bars 挂上 symbol 对应的前收、涨停价、跌停价。返回新 DataFrame。"""
    df = bars.copy()
    df["prev_close"] = df["symbol"].map(prev_close)
    df["limit_up_price"] = _limit_up_price(df["prev_close"])
    df["limit_down_price"] = _limit_down_price(df["prev_close"])
    return df


def limit_up_down_counts(bars: pd.DataFrame, prev_close: pd.Series) -> pd.DataFrame:
    """per trade_date 涨跌停家数与涨跌家数。

    bars：长格式（trade_date/symbol/open/high/low/close）。
    prev_close：index=symbol 的前收序列，用于算涨跌停阈值。
    涨停：high==涨停价（触及）且 close≈涨停价（收盘封）。
    返回 index=trade_date 的 DataFrame，列：limit_up_count/limit_down_count/advance/decline。
    """
    df = _attach_limit_prices(bars, prev_close)
    df["is_limit_up"] = (df["high"] == df["limit_up_price"]) & (df["close"] == df["limit_up_price"])
    df["is_limit_down"] = (df["low"] == df["limit_down_price"]) & (df["close"] == df["limit_down_price"])
    df["is_advance"] = df["close"] > df["prev_close"]
    df["is_decline"] = df["close"] < df["prev_close"]
    grouped = df.groupby("trade_date").agg(
        limit_up_count=("is_limit_up", "sum"),
        limit_down_count=("is_limit_down", "sum"),
        advance=("is_advance", "sum"),
        decline=("is_decline", "sum"),
    )
    # groupby sum 返回数值类型，转为 int
    return grouped.astype(int)


def consecutive_board_height(bars: pd.DataFrame, prev_close_map: dict) -> pd.Series:
    """per symbol 当前（最新 trade_date）连续涨停天数。

    bars：长格式（trade_date/symbol/...）。
    prev_close_map：{symbol: {trade_date: 前收}}，逐日前收用于算每日涨停价。
    涨停判定（简化）：close >= 涨停价。逐日连续计数，断则归零。
    返回 index=symbol 的 int Series；未涨停为 0。
    """
    if len(bars) == 0:
        return pd.Series(dtype=int, name="board_height")

    # 展平 prev_close_map 为 (symbol, trade_date) -> 前收
    pc_rows = [
        {"symbol": s, "trade_date": d, "prev_close": v}
        for s, m in prev_close_map.items()
        for d, v in m.items()
    ]
    pc = pd.DataFrame(pc_rows)
    df = bars.merge(pc, on=["symbol", "trade_date"], how="left")
    df["limit_up_price"] = _limit_up_price(df["prev_close"])
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    df["is_limit"] = df["close"] >= df["limit_up_price"]

    def _height(mask: pd.Series) -> int:
        """从末尾向前数连续 True 的长度。"""
        h = 0
        for v in mask.iloc[::-1]:
            if bool(v):
                h += 1
            else:
                break
        return h

    height = df.groupby("symbol")["is_limit"].apply(_height).astype(int)
    height.name = "board_height"
    height.index.name = "symbol"
    return height


def seal_rate(bars: pd.DataFrame, prev_close: pd.Series) -> float:
    """封板率 = 触及涨停且收盘仍封的家数 / 触及涨停家数（取最新 trade_date）。

    触及涨停：high==涨停价。收盘封：close==涨停价。
    无触及涨停时返回 0.0（明确语义，避免零除）。
    """
    df = _attach_limit_prices(bars, prev_close)
    if len(df) == 0:
        return 0.0
    latest = df["trade_date"].max()
    day = df[df["trade_date"] == latest]
    touched = (day["high"] == day["limit_up_price"]).sum()
    if touched == 0:
        return 0.0
    sealed = ((day["high"] == day["limit_up_price"]) & (day["close"] == day["limit_up_price"])).sum()
    return float(sealed) / float(touched)


def breadth_factor_series(
    bars: pd.DataFrame, prev_close_series: pd.DataFrame
) -> pd.DataFrame:
    """per trade_date 市场宽度因子 = (涨停 - 跌停) / 总家数。

    bars：长格式行情。
    prev_close_series：长格式（trade_date/symbol/prev_close），逐日前收。
    返回 DataFrame(trade_date, breadth_value)，按 trade_date 升序。
    """
    # prev_close_series 展平为 (trade_date, symbol) -> prev_close
    df = bars.merge(
        prev_close_series[["trade_date", "symbol", "prev_close"]],
        on=["trade_date", "symbol"],
        how="left",
    )
    df["limit_up_price"] = _limit_up_price(df["prev_close"])
    df["limit_down_price"] = _limit_down_price(df["prev_close"])
    df["is_limit_up"] = (df["high"] == df["limit_up_price"]) & (df["close"] == df["limit_up_price"])
    df["is_limit_down"] = (df["low"] == df["limit_down_price"]) & (df["close"] == df["limit_down_price"])

    g = df.groupby("trade_date").agg(
        up=("is_limit_up", "sum"),
        down=("is_limit_down", "sum"),
        total=("symbol", "size"),
    )
    out = pd.DataFrame({
        "trade_date": g.index,
        "breadth_value": (g["up"] - g["down"]) / g["total"],
    }).reset_index(drop=True)
    return out
