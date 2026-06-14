"""Factor Protocol + FactorRegistry 测试（设计 v0.5 §4.2.1）。

覆盖点：
- register/get 往返；未注册 get 抛 KeyError；同名覆盖注册
- compute_panel 装配 FactorContext 并汇总为 DataFrame（index=symbol，列=因子名）
- names 含未注册因子 → KeyError
- PIT 由 FactorContext 强制（间接验证 ctx 生效；过滤语义下未来可得 symbol 不进入结果）
- universe 过滤：结果 index 仅含 universe 内 symbol

TDD：本文件先于 registry.py 编写，import 失败为预期红线。
PIT 不在 registry 重复实现，由 FactorContext（A1）强制，registry 仅装配 ctx。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from quant.factor.context import FactorContext
from quant.factor.registry import Factor, FactorRegistry


# ---------------------------------------------------------------------------
# 合成 panel
# ---------------------------------------------------------------------------
# 三只 symbol，两日 close：
#   - 000001.SZ / 600000.SH / 300001.SZ，T 与 T+1 各一行
#   - available_at = trade_date 当日 15:00（收盘后可得）
#   - 所有 T+1 行 available_at=T+1 15:00，对 T 日决策而言均为未来
T = _dt.datetime(2024, 1, 5)
T_NEXT = _dt.datetime(2024, 1, 6)


def _build_panel() -> pd.DataFrame:
    rows = [
        {"symbol": "000001.SZ", "trade_date": T.date(), "available_at": T.replace(hour=15, minute=0), "close": 10.0},
        {"symbol": "000001.SZ", "trade_date": T_NEXT.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 11.0},
        {"symbol": "600000.SH", "trade_date": T.date(), "available_at": T.replace(hour=15, minute=0), "close": 20.0},
        {"symbol": "600000.SH", "trade_date": T_NEXT.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 21.0},
        {"symbol": "300001.SZ", "trade_date": T.date(), "available_at": T.replace(hour=15, minute=0), "close": 30.0},
        {"symbol": "300001.SZ", "trade_date": T_NEXT.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 31.0},
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 假因子（duck typing 满足 Factor Protocol）
# ---------------------------------------------------------------------------
class _FakeClose:
    name = "fake_close"
    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        # 每 symbol PIT 可得最新 close
        return ctx.latest("close")


class _FakeDouble:
    name = "fake_double"
    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        return ctx.latest("close") * 2


@pytest.fixture
def panel() -> pd.DataFrame:
    return _build_panel()


@pytest.fixture
def registry() -> FactorRegistry:
    reg = FactorRegistry()
    reg.register(_FakeClose())
    reg.register(_FakeDouble())
    return reg


# ---------------------------------------------------------------------------
# 1. register / get 往返
# ---------------------------------------------------------------------------
def test_register_and_get():
    reg = FactorRegistry()
    f = _FakeClose()
    reg.register(f)
    assert reg.get("fake_close") is f


def test_get_unknown_raises_keyerror():
    reg = FactorRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_register_overwrites_same_name():
    reg = FactorRegistry()
    first = _FakeClose()
    second = _FakeClose()
    reg.register(first)
    reg.register(second)
    # 同名覆盖：get 返回最后注册的实例
    assert reg.get("fake_close") is second


# ---------------------------------------------------------------------------
# 2. compute_panel 装配 DataFrame
# ---------------------------------------------------------------------------
def test_compute_panel_assembles_dataframe(registry: FactorRegistry, panel: pd.DataFrame):
    df = registry.compute_panel(
        names=["fake_close", "fake_double"],
        t=T.replace(hour=16, minute=0),  # T 日 16:00 决策
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-20240105-1600",
        panel=panel,
    )
    # 形态：index=symbol，列=因子名
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["fake_close", "fake_double"]
    assert set(df.index) == {"000001.SZ", "600000.SH", "300001.SZ"}
    # fake_double == 2 × fake_close（T 日 close，T+1 为 PIT 未来被过滤）
    assert df.loc["000001.SZ", "fake_close"] == 10.0
    assert df.loc["000001.SZ", "fake_double"] == 20.0
    assert df.loc["600000.SH", "fake_close"] == 20.0
    assert df.loc["600000.SH", "fake_double"] == 40.0


# ---------------------------------------------------------------------------
# 3. names 含未注册因子 → KeyError
# ---------------------------------------------------------------------------
def test_compute_panel_unknown_factor_raises(registry: FactorRegistry, panel: pd.DataFrame):
    with pytest.raises(KeyError):
        registry.compute_panel(
            names=["fake_close", "ghost"],
            t=T.replace(hour=16, minute=0),
            universe=["000001.SZ"],
            snapshot_id="snap-x",
            panel=panel,
        )


# ---------------------------------------------------------------------------
# 4. PIT 由 FactorContext 强制（间接验证 ctx 生效）
# ---------------------------------------------------------------------------
def test_compute_panel_pit_enforced(registry: FactorRegistry, panel: pd.DataFrame):
    # decision_time 早于 T 日 15:00：所有行 available_at > t → 无 PIT 可得行
    # latest 返回空 → 该列因子值为空 Series，panel 装配后该列无行
    df = registry.compute_panel(
        names=["fake_close"],
        t=T.replace(hour=10, minute=0),  # T 日 10:00，早于所有 available_at
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-early",
        panel=panel,
    )
    # PIT 过滤下无任何可得行 → 结果空（间接证明 ctx 在 compute 链路中生效）
    assert df.empty


# ---------------------------------------------------------------------------
# 5. universe 过滤：结果 index 仅含 universe 内 symbol
# ---------------------------------------------------------------------------
def test_universe_applied(registry: FactorRegistry, panel: pd.DataFrame):
    df = registry.compute_panel(
        names=["fake_close", "fake_double"],
        t=T.replace(hour=16, minute=0),
        universe=["000001.SZ", "600000.SH"],  # 仅 2 个
        snapshot_id="snap-universe",
        panel=panel,
    )
    assert set(df.index) == {"000001.SZ", "600000.SH"}
    assert "300001.SZ" not in df.index
