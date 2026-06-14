"""DSL 算子集测试（设计 v0.5 §4.3.3）。

覆盖点（对照 pandas 参考实现，per symbol 时序 / per trade_date 横截面）：
- 时序：ts_mean / delay / ts_delta / ts_rank / ts_max / ts_std / ts_corr / decay_linear
- 横截面：rank / zscore / winsorize / scale / group_neutral
- 算术：signed_power

合成 panel：3 symbol × 10 trade_date，close/volume 已知模式。

TDD：本文件先于 quant/dsl/operators.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.dsl.operators import (
    decay_linear,
    delay,
    group_neutral,
    quantile,
    rank,
    scale,
    signed_power,
    ts_corr,
    ts_delta,
    ts_max,
    ts_mean,
    ts_rank,
    ts_std,
    winsorize,
    zscore,
)


# ---------------------------------------------------------------------------
# 合成 panel：3 symbol × 10 trade_date
# ---------------------------------------------------------------------------
# symbol0：close = 10 + 0.5*j（线性）
# symbol1：close = 20 - 0.5*j（线性反向）
# symbol2：close = 5,6,7,...,14
# volume：close * 1000 + j，给 ts_corr 用
def _build_panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    rows = []
    for sym, base, step in [("S0", 10.0, 0.5), ("S1", 20.0, -0.5), ("S2", 5.0, 1.0)]:
        for j, d in enumerate(dates):
            close = base + step * j
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": d,
                    "close": close,
                    "volume": close * 1000 + j,
                }
            )
    df = pd.DataFrame(rows).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return df


@pytest.fixture
def panel() -> pd.DataFrame:
    return _build_panel()


# ===========================================================================
# 时序算子（per symbol，沿 trade_date rolling）
# ===========================================================================
def test_ts_mean(panel: pd.DataFrame) -> None:
    n = 3
    got = ts_mean(panel, "close", n)
    # 参考：groupby symbol rolling n mean
    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .transform(lambda s: s.rolling(n, min_periods=n).mean())
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_ts_mean_aligned_index(panel: pd.DataFrame) -> None:
    # 返回 Series 与 df 索引对齐、长度一致
    got = ts_mean(panel, "close", 3)
    assert len(got) == len(panel)


def test_delay(panel: pd.DataFrame) -> None:
    got = delay(panel, "close", 1)
    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .shift(1)
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )
    # 每个 symbol 首行必为 NaN
    first_rows = panel.sort_values(["symbol", "trade_date"]).groupby("symbol").head(1)
    assert got.loc[first_rows.index].isna().all()


def test_ts_delta(panel: pd.DataFrame) -> None:
    n = 2
    got = ts_delta(panel, "close", n)
    delayed = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .shift(n)
    )
    expected = panel["close"] - delayed
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_ts_rank(panel: pd.DataFrame) -> None:
    n = 3
    got = ts_rank(panel, "close", n)
    # 参考：窗口内当前值的 pct rank（rank 平均法 / n），即 rolling().rank(pct=True)
    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .transform(lambda s: s.rolling(n, min_periods=n).rank(pct=True))
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_ts_max(panel: pd.DataFrame) -> None:
    n = 4
    got = ts_max(panel, "close", n)
    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .transform(lambda s: s.rolling(n, min_periods=n).max())
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_ts_std(panel: pd.DataFrame) -> None:
    n = 5
    got = ts_std(panel, "close", n)
    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .transform(lambda s: s.rolling(n, min_periods=n).std(ddof=0))
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_ts_corr(panel: pd.DataFrame) -> None:
    n = 5
    got = ts_corr(panel, "close", "volume", n)
    # 参考：per symbol rolling corr
    def _rolling_corr(g: pd.DataFrame) -> pd.Series:
        return g["close"].rolling(n, min_periods=n).corr(g["volume"])

    sorted_df = panel.sort_values(["symbol", "trade_date"])
    expected = sorted_df.groupby("symbol", group_keys=False).apply(_rolling_corr)
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_decay_linear(panel: pd.DataFrame) -> None:
    n = 3
    got = decay_linear(panel, "close", n)
    # 权重 n,n-1,...,1 归一化，加权均
    weights = np.arange(n, 0, -1, dtype=float)
    weights = weights / weights.sum()

    def _wmean(s: pd.Series) -> float:
        return float(np.dot(s.values, weights))

    expected = (
        panel.sort_values(["symbol", "trade_date"])
        .groupby("symbol")["close"]
        .transform(
            lambda s: s.rolling(n, min_periods=n).apply(_wmean, raw=False)
        )
    )
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


# ===========================================================================
# 横截面算子（per trade_date，跨 symbol）
# ===========================================================================
def test_rank(panel: pd.DataFrame) -> None:
    src = panel["close"]
    got = rank(panel, src)
    expected = panel.groupby("trade_date")["close"].rank(pct=True)
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_zscore(panel: pd.DataFrame) -> None:
    src = panel["close"]
    got = zscore(panel, src)
    grp = panel.groupby("trade_date")["close"]
    mean = grp.transform("mean")
    std = grp.transform("std", ddof=0)
    expected = (panel["close"] - mean) / std
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_quantile(panel: pd.DataFrame) -> None:
    src = panel["close"]
    got = quantile(panel, src, 0.5)
    # 参考：每个 trade_date 内的按位置分位（0..1，rank/(n)）
    grp = panel.groupby("trade_date")["close"]
    ranks = grp.rank(method="average")
    counts = grp.transform("size")
    expected = (ranks - 1) / counts
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_winsorize(panel: pd.DataFrame) -> None:
    # 构造含明显离群点的数据
    df = panel.copy()
    df.loc[df.index[0], "close"] = 1000.0  # 极大
    df.loc[df.index[1], "close"] = -1000.0  # 极小
    src = df["close"]
    got = winsorize(df, src, limits=0.1)
    # 参考：per trade_date 内裁剪到 [10% 分位, 90% 分位]
    grp = df.groupby("trade_date")["close"]
    lo = grp.transform(lambda s: s.quantile(0.1))
    hi = grp.transform(lambda s: s.quantile(0.9))
    expected = df["close"].clip(lower=lo, upper=hi)
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


def test_scale(panel: pd.DataFrame) -> None:
    src = panel["close"]
    got = scale(panel, src)
    # 参考：per trade_date 缩放使 abs 和 = 1
    grp = panel.groupby("trade_date")["close"]
    abs_sum = grp.transform(lambda s: s.abs().sum())
    expected = panel["close"] / abs_sum
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )
    # 验证每个日期 abs 和 = 1
    check = pd.concat([panel["trade_date"], got], axis=1)
    check.columns = ["trade_date", "v"]
    sums = check.groupby("trade_date")["v"].apply(lambda s: s.abs().sum())
    np.testing.assert_allclose(sums.values, 1.0)


def test_group_neutral(panel: pd.DataFrame) -> None:
    # 加一列分组字段：symbol 按奇偶分两组（跨 trade_date）
    df = panel.copy()
    df["g"] = (df["symbol"].astype(str).str[-1].astype(int) % 2).astype("int64")
    src = df["close"]
    got = group_neutral(df, src, "g")
    # 参考：per (trade_date, g) 去均值
    grp = df.groupby(["trade_date", "g"])["close"]
    expected = df["close"] - grp.transform("mean")
    pd.testing.assert_series_equal(
        got.reset_index(drop=True), expected.reset_index(drop=True), check_names=False
    )


# ===========================================================================
# 算术
# ===========================================================================
def test_signed_power() -> None:
    s = pd.Series([-2.0, -1.0, 0.0, 1.0, 2.0])
    e = 2.0
    got = signed_power(s, e)
    expected = np.sign(s) * (np.abs(s) ** e)
    pd.testing.assert_series_equal(got, expected, check_names=False)
