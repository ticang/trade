"""基础因子（动量/反转/波动率）测试（设计 v0.5 §4.2.2）。

覆盖点：
- MomentumFactor(window)：N 日收益率 = latest_close / close_{N日前} - 1，对照参考实现
- ReversalFactor(window) = -MomentumFactor(window)
- VolatilityFactor(window)：N 日收益 std，对照参考实现
- Factor Protocol 一致（name/factor_version/inputs/compute）+ 注册后 compute_panel 可用
- 数据不足（历史 < window+1）→ NaN
- PIT 经 ctx（decision_time 早 → 仅用可得数据）

TDD：本文件先于 factors/ 实现编写，import 失败为预期红线。
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from quant.factor.context import FactorContext
from quant.factor.factors.momentum import MomentumFactor, ReversalFactor
from quant.factor.factors.volatility import VolatilityFactor
from quant.factor.registry import FactorRegistry


# ---------------------------------------------------------------------------
# 合成 panel：3 symbol × 30 交易日，known 模式
# ---------------------------------------------------------------------------
# symbol0：close = 10 + 0.1*j（线性）
# symbol1：close = 10 * 1.01**j（指数，正收益）
# symbol2：仅 5 日历史（数据不足测试），close = 5 + 0.1*j
# trade_date：连续 30 个工作日（2024-01-01 起，跳过周末）
# available_at = trade_date 15:00（当日收盘后可得）
def _trading_dates(n: int) -> list[_dt.date]:
    """生成 n 个连续工作日（跳过周末）。"""
    out: list[_dt.date] = []
    d = _dt.date(2024, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:  # 周一..周五
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


DATES = _trading_dates(30)
LAST_DATE = DATES[-1]
DECISION_TIME = _dt.datetime(LAST_DATE.year, LAST_DATE.month, LAST_DATE.day, 16, 0)


def _close_series(mode: str, n: int) -> np.ndarray:
    """按模式生成 n 个 close 值。"""
    j = np.arange(n)
    if mode == "linear":
        return 10.0 + 0.1 * j
    if mode == "exp":
        return 10.0 * 1.01 ** j
    if mode == "short":  # 仅前 5 日有效，其余 NaN
        v = 5.0 + 0.1 * j
        v[5:] = np.nan
        return v
    raise ValueError(mode)


def _build_panel() -> pd.DataFrame:
    rows: list[dict] = []
    specs = [
        ("000001.SZ", "linear"),
        ("600000.SH", "exp"),
        ("300001.SZ", "short"),
    ]
    for symbol, mode in specs:
        closes = _close_series(mode, len(DATES))
        for d, c in zip(DATES, closes):
            if np.isnan(c):
                continue
            rows.append({
                "symbol": symbol,
                "trade_date": d,
                "available_at": _dt.datetime(d.year, d.month, d.day, 15, 0),
                "close": float(c),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def panel() -> pd.DataFrame:
    return _build_panel()


@pytest.fixture
def ctx(panel: pd.DataFrame) -> FactorContext:
    return FactorContext(
        decision_time=DECISION_TIME,
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-basic-factors",
        panel=panel,
    )


def _panel_reference_momentum(panel: pd.DataFrame, window: int) -> pd.Series:
    """参考实现：per symbol close[-1]/close[-window-1] - 1。"""
    out = {}
    for symbol, sub in panel.groupby("symbol"):
        sub = sub.sort_values("trade_date")
        c = sub["close"].to_numpy()
        if len(c) < window + 1:
            out[symbol] = np.nan
        else:
            out[symbol] = c[-1] / c[-window - 1] - 1.0
    return pd.Series(out)


def _panel_reference_volatility(panel: pd.DataFrame, window: int) -> pd.Series:
    """参考实现：per symbol 最近 window+1 个 close 的日收益 std。"""
    out = {}
    for symbol, sub in panel.groupby("symbol"):
        sub = sub.sort_values("trade_date")
        c = sub["close"].to_numpy()
        if len(c) < window + 1:
            out[symbol] = np.nan
        else:
            rets = np.diff(c[-(window + 1):]) / c[-(window + 1):-1]
            out[symbol] = float(np.std(rets, ddof=1))
    return pd.Series(out)


# ---------------------------------------------------------------------------
# 1. MomentumFactor 值对照参考
# ---------------------------------------------------------------------------
def test_momentum_value(ctx: FactorContext, panel: pd.DataFrame):
    window = 20
    f = MomentumFactor(window=window)
    s = f.compute(ctx)
    # index=symbol
    assert s.index.name == "symbol"
    # 充足历史的 symbol 值匹配参考
    ref = _panel_reference_momentum(panel, window)
    for symbol in ["000001.SZ", "600000.SZ" if False else "600000.SH"]:
        np.testing.assert_allclose(s[symbol], ref[symbol], rtol=1e-10)
    # 元信息
    assert f.name == f"momentum_{window}"
    assert f.factor_version == "v1"
    assert f.inputs == ["close"]


# ---------------------------------------------------------------------------
# 2. ReversalFactor = -MomentumFactor
# ---------------------------------------------------------------------------
def test_reversal_is_negative_momentum(ctx: FactorContext):
    window = 5
    rev = ReversalFactor(window=window).compute(ctx)
    mom = MomentumFactor(window=window).compute(ctx)
    # 对齐 symbol 后逐项相等（含 NaN：NaN == -NaN 仍为 NaN，用 allclose equal_nan）
    aligned = rev.index.intersection(mom.index)
    np.testing.assert_allclose(
        rev.loc[aligned].to_numpy(),
        (-mom.loc[aligned]).to_numpy(),
        rtol=1e-12,
        equal_nan=True,
    )
    assert ReversalFactor(window=window).name == f"reversal_{window}"


# ---------------------------------------------------------------------------
# 3. VolatilityFactor 值对照参考
# ---------------------------------------------------------------------------
def test_volatility_value(ctx: FactorContext, panel: pd.DataFrame):
    window = 20
    f = VolatilityFactor(window=window)
    s = f.compute(ctx)
    assert s.index.name == "symbol"
    ref = _panel_reference_volatility(panel, window)
    # 线性/指数序列日收益近常数，std 量级 ~1e-16，纯 rtol 会放大机器精度差异；
    # 加 atol 容纳浮点噪声，rtol 仍严格保证算法一致
    for symbol in ["000001.SZ", "600000.SH"]:
        np.testing.assert_allclose(s[symbol], ref[symbol], rtol=1e-10, atol=1e-12)
    assert f.name == f"volatility_{window}"
    assert f.factor_version == "v1"
    assert f.inputs == ["close"]


# ---------------------------------------------------------------------------
# 4. Factor Protocol 一致 + 注册后 compute_panel 可用
# ---------------------------------------------------------------------------
def test_factor_protocol_conformance():
    factors = [MomentumFactor(20), ReversalFactor(5), VolatilityFactor(20)]
    for f in factors:
        assert hasattr(f, "name") and isinstance(f.name, str)
        assert hasattr(f, "factor_version") and isinstance(f.factor_version, str)
        assert hasattr(f, "inputs") and f.inputs == ["close"]
        assert callable(getattr(f, "compute", None))


def test_factors_in_registry_compute_panel(panel: pd.DataFrame):
    reg = FactorRegistry()
    reg.register(MomentumFactor(20))
    reg.register(VolatilityFactor(20))
    df = reg.compute_panel(
        names=["momentum_20", "volatility_20"],
        t=DECISION_TIME,
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-int",
        panel=panel,
    )
    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) == {"momentum_20", "volatility_20"}
    assert set(df.index) == {"000001.SZ", "600000.SH", "300001.SZ"}
    # 300001.SZ 仅 5 日历史 → momentum_20 / volatility_20 为 NaN
    assert pd.isna(df.loc["300001.SZ", "momentum_20"])
    assert pd.isna(df.loc["300001.SZ", "volatility_20"])


# ---------------------------------------------------------------------------
# 5. 数据不足 → NaN
# ---------------------------------------------------------------------------
def test_insufficient_history_nan(ctx: FactorContext):
    # 300001.SZ 仅 5 日历史，MomentumFactor(20) 需要 21 日 → NaN
    s = MomentumFactor(window=20).compute(ctx)
    assert pd.isna(s["300001.SZ"])
    # VolatilityFactor(20) 同理
    v = VolatilityFactor(window=20).compute(ctx)
    assert pd.isna(v["300001.SZ"])
    # 充足历史 symbol 仍有效
    assert not pd.isna(s["000001.SZ"])
    assert not pd.isna(v["000001.SZ"])


# ---------------------------------------------------------------------------
# 6. PIT 经 ctx：decision_time 早 → 仅用可得数据
# ---------------------------------------------------------------------------
def test_pit_respected(panel: pd.DataFrame):
    # decision_time 设为 DATES[10] 当日 16:00：仅前 10 个 trade_date PIT 可得
    early = DATES[10]
    early_dt = _dt.datetime(early.year, early.month, early.day, 16, 0)
    ctx = FactorContext(
        decision_time=early_dt,
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-early",
        panel=panel,
    )
    # MomentumFactor(20) 需 21 日，此刻仅 10 日可得 → 全 NaN（间接证明 PIT 过滤生效）
    s = MomentumFactor(window=20).compute(ctx)
    assert pd.isna(s["000001.SZ"])
    # 但用更小 window=5（需 6 日，此刻有 10 日）应能算出
    s5 = MomentumFactor(window=5).compute(ctx)
    assert not pd.isna(s5["000001.SZ"])
    # 且该值等于仅用前 10 日数据的参考
    pit_panel = panel[panel["trade_date"].isin(DATES[:11])]
    ref = _panel_reference_momentum(pit_panel, 5)
    np.testing.assert_allclose(s5["000001.SZ"], ref["000001.SZ"], rtol=1e-10)
