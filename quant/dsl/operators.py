"""DSL 算子集（设计 v0.5 §4.3.3）。

参考 WorldQuant Brain 风格，全部向量化（pandas/numpy），无逐元素 Python 循环。
数据形态：长格式 panel，含 symbol / trade_date / <字段>。
- 时序算子：per symbol，沿 trade_date rolling；签名 (df, field, n) -> Series（与 df 对齐）
- 横截面算子：per trade_date，跨 symbol；签名 (df, series, ...) -> Series
- 算术算子：series 级
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "ts_mean",
    "delay",
    "ts_delta",
    "ts_rank",
    "ts_max",
    "ts_std",
    "ts_corr",
    "decay_linear",
    "rank",
    "zscore",
    "quantile",
    "winsorize",
    "scale",
    "group_neutral",
    "signed_power",
    "add",
    "sub",
    "mul",
    "div",
]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _sorted_copy(df: pd.DataFrame) -> pd.DataFrame:
    """排序为 symbol/trade_date 升序，保证 rolling 顺序确定。"""
    return df.sort_values(["symbol", "trade_date"])


def _by_symbol(sdf: pd.DataFrame, field: str) -> pd.Series:
    """per symbol 分组的字段 Series（groupby transform 友好）。"""
    return sdf.groupby("symbol", group_keys=False)[field]


# ---------------------------------------------------------------------------
# 时序算子
# ---------------------------------------------------------------------------
def ts_mean(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """N 日滚动均值（per symbol，不足窗口返回 NaN）。"""
    sdf = _sorted_copy(df)
    return _by_symbol(sdf, field).transform(lambda s: s.rolling(n, min_periods=n).mean())


def delay(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """N 日前的值（per symbol shift）。"""
    sdf = _sorted_copy(df)
    return _by_symbol(sdf, field).shift(n)


def ts_delta(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """当前值减 N 日前值：x - delay(x, n)。"""
    sdf = _sorted_copy(df)
    shifted = _by_symbol(sdf, field).shift(n)
    return sdf[field] - shifted


def ts_rank(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """窗口内当前值的 pct rank（升序，平均法）。"""
    sdf = _sorted_copy(df)

    def _pct(s: pd.Series) -> pd.Series:
        return s.rolling(n, min_periods=n).rank(pct=True)

    return _by_symbol(sdf, field).transform(_pct)


def ts_max(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """N 日滚动最大值（per symbol）。"""
    sdf = _sorted_copy(df)
    return _by_symbol(sdf, field).transform(lambda s: s.rolling(n, min_periods=n).max())


def ts_std(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """N 日滚动标准差（per symbol，总体 std ddof=0）。"""
    sdf = _sorted_copy(df)
    return _by_symbol(sdf, field).transform(
        lambda s: s.rolling(n, min_periods=n).std(ddof=0)
    )


def ts_corr(
    df: pd.DataFrame, field_x: str, field_y: str, n: int
) -> pd.Series:
    """两字段 N 日滚动相关系数（per symbol）。"""
    sdf = _sorted_copy(df)

    def _rolling_corr(g: pd.DataFrame) -> pd.Series:
        return g[field_x].rolling(n, min_periods=n).corr(g[field_y])

    return sdf.groupby("symbol", group_keys=False).apply(_rolling_corr)


def decay_linear(df: pd.DataFrame, field: str, n: int) -> pd.Series:
    """线性衰减加权均（权重 n,n-1,...,1 归一化，越近权重越大）。"""
    sdf = _sorted_copy(df)
    weights = np.arange(n, 0, -1, dtype=float)
    weights = weights / weights.sum()

    def _wmean(s: pd.Series) -> pd.Series:
        return s.rolling(n, min_periods=n).apply(
            lambda w: float(np.dot(w, weights)), raw=True
        )

    return _by_symbol(sdf, field).transform(_wmean)


# ---------------------------------------------------------------------------
# 横截面算子（per trade_date）
# ---------------------------------------------------------------------------
def rank(df: pd.DataFrame, series: pd.Series) -> pd.Series:
    """per trade_date pct rank（升序，平均法）。"""
    g = df.groupby("trade_date")
    return series.groupby([df["trade_date"]]).rank(pct=True)


def zscore(df: pd.DataFrame, series: pd.Series) -> pd.Series:
    """per trade_date z-score：(x-mean)/std（ddof=0）。"""
    grp = series.groupby(df["trade_date"])
    mean = grp.transform("mean")
    std = grp.transform("std", ddof=0)
    return (series - mean) / std


def quantile(df: pd.DataFrame, series: pd.Series, q: float) -> pd.Series:
    """per trade_date 位置分位 [0,1]：rank/(n)（rank 平均法）。"""
    grp = series.groupby(df["trade_date"])
    ranks = grp.rank(method="average")
    counts = grp.transform("size")
    return (ranks - 1) / counts


def winsorize(
    df: pd.DataFrame, series: pd.Series, limits: float = 0.05
) -> pd.Series:
    """per trade_date 双尾裁剪：缩到 [limits, 1-limits] 分位区间。"""
    grp = series.groupby(df["trade_date"])
    lo = grp.transform(lambda s: s.quantile(limits))
    hi = grp.transform(lambda s: s.quantile(1 - limits))
    return series.clip(lower=lo, upper=hi)


def scale(df: pd.DataFrame, series: pd.Series) -> pd.Series:
    """per trade_date 缩放使 abs 和 = 1。"""
    grp = series.groupby(df["trade_date"])
    abs_sum = grp.transform(lambda s: s.abs().sum())
    return series / abs_sum


def group_neutral(
    df: pd.DataFrame, series: pd.Series, group_field: str
) -> pd.Series:
    """分组去均值：per (trade_date, group_field) 减组内均值。"""
    grp = series.groupby([df["trade_date"], df[group_field]])
    return series - grp.transform("mean")


# ---------------------------------------------------------------------------
# 算术
# ---------------------------------------------------------------------------
def signed_power(series: pd.Series, e: float) -> pd.Series:
    """保号乘幂：sign(x) * |x|^e。"""
    return np.sign(series) * (np.abs(series) ** e)


# 双 series 算术：向量化，结果与入参对齐；div 零除沿用 pandas inf/nan 自然行为
def add(x: pd.Series, y: pd.Series) -> pd.Series:
    """series 逐元素加。"""
    return x + y


def sub(x: pd.Series, y: pd.Series) -> pd.Series:
    """series 逐元素减。"""
    return x - y


def mul(x: pd.Series, y: pd.Series) -> pd.Series:
    """series 逐元素乘。"""
    return x * y


def div(x: pd.Series, y: pd.Series) -> pd.Series:
    """series 逐元素除；零除自然得 inf/nan。"""
    return x / y
