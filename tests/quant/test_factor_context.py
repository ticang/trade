"""FactorContext PIT 强制测试（设计 v0.5 §4.2.2 / §4.7.6）。

覆盖点：
- field 过滤 available_at > decision_time 的未来行
- latest 不返回未来才可用的行
- universe 过滤：只暴露 universe 内 symbol
- point 单点查询未来行 → 抛 LookAheadError
- snapshot_id 透传

TDD：本文件先于 context.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from quant.factor.context import FactorContext, LookAheadError


# ---------------------------------------------------------------------------
# 合成 panel 构造
# ---------------------------------------------------------------------------
# 三只 symbol，两日 bar：
#   - 000001.SZ / 600000.SH 在 universe 内；300001.SZ 不在
#   - T 日行 available_at = T 15:00（T 日收盘后可得）
#   - 600000.SH 的 T 日行 available_at = T+1 09:00（次日才可得 → 决策日 T 时为未来）
#   - 所有 symbol 的 T+1 行 available_at = T+1 15:00（对决策日 T 而言全为未来）
T = _dt.datetime(2024, 1, 5)
T_NEXT = _dt.datetime(2024, 1, 6)


def _build_panel() -> pd.DataFrame:
    rows = [
        # 000001.SZ：T 日可得（15:00），T+1 日可得（次日 15:00）
        {"symbol": "000001.SZ", "trade_date": T.date(), "available_at": T.replace(hour=15, minute=0), "close": 10.0},
        {"symbol": "000001.SZ", "trade_date": T_NEXT.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 11.0},
        # 600000.SH：T 日行次日 09:00 才可得（未来）；T+1 行更远未来
        {"symbol": "600000.SH", "trade_date": T.date(), "available_at": _dt.datetime(2024, 1, 6, 9, 0), "close": 20.0},
        {"symbol": "600000.SH", "trade_date": T_NEXT.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 21.0},
        # 300001.SZ：T 日可得（15:00），但不在 universe 内
        {"symbol": "300001.SZ", "trade_date": T.date(), "available_at": T.replace(hour=15, minute=0), "close": 30.0},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def ctx() -> FactorContext:
    return FactorContext(
        decision_time=T.replace(hour=16, minute=0),  # T 日 16:00 决策
        universe=["000001.SZ", "600000.SH"],
        snapshot_id="snap-20240105-1600",
        panel=_build_panel(),
    )


# ---------------------------------------------------------------------------
# 1. field 过滤未来数据
# ---------------------------------------------------------------------------
def test_field_filters_future_data(ctx: FactorContext):
    # decision_time=T 16:00：仅 000001.SZ T 日行（15:00 可得）应进入 field/close
    # 600000.SH T 日行 available_at=T+1 09:00 > decision_time → 被过滤
    # 000001.SZ T+1 行 available_at=T+1 15:00 > decision_time → 被过滤
    df = ctx.field("close")
    assert set(df["symbol"]) == {"000001.SZ"}
    # 仅 T 日行，close=10.0
    assert len(df) == 1
    assert df.iloc[0]["close"] == 10.0
    assert df.iloc[0]["trade_date"] == T.date()


# ---------------------------------------------------------------------------
# 2. latest 不返回未来行（PIT 间接验证）
# ---------------------------------------------------------------------------
def test_latest_excludes_future_available_rows(ctx: FactorContext):
    # 000001.SZ：T 日 close=10.0 可得，T+1 close=11.0 不可得 → latest=10.0
    # 600000.SH：T 日行 available_at 在未来 → latest 为 NaN（无 PIT 安全可得行）
    s = ctx.latest("close")
    assert s["000001.SZ"] == 10.0
    # 600000.SH 无任何 available_at<=decision_time 的行 → 缺失/NaN
    assert "600000.SH" not in s.index or pd.isna(s.get("600000.SH"))


def test_lookahead_guard_via_latest_all_future():
    # 极端构造：全部行 available_at > decision_time → latest 应返回空，不崩溃
    panel = pd.DataFrame([
        {"symbol": "000001.SZ", "trade_date": T.date(), "available_at": T_NEXT.replace(hour=15, minute=0), "close": 99.0},
    ])
    ctx = FactorContext(
        decision_time=T.replace(hour=16, minute=0),
        universe=["000001.SZ"],
        snapshot_id="snap-all-future",
        panel=panel,
    )
    s = ctx.latest("close")
    assert len(s) == 0
    # field 同样返回空（过滤语义，不抛）
    assert len(ctx.field("close")) == 0


# ---------------------------------------------------------------------------
# 3. universe 过滤
# ---------------------------------------------------------------------------
def test_field_only_contains_universe_symbols(ctx: FactorContext):
    # 300001.SZ 不在 universe，即便 PIT 可得也不暴露
    df = ctx.field("close")
    assert "300001.SZ" not in set(df["symbol"])
    # 即便 universe 外的 symbol PIT 可得，latest 也不含
    s = ctx.latest("close")
    assert "300001.SZ" not in s.index


# ---------------------------------------------------------------------------
# 4. point 单点查询未来行 → LookAheadError
# ---------------------------------------------------------------------------
def test_point_lookahead_raises(ctx: FactorContext):
    # 600000.SH T 日行 available_at=T+1 09:00 > decision_time → 抛 LookAheadError
    with pytest.raises(LookAheadError):
        ctx.point("600000.SH", "close", T.date())


def test_point_returns_value_when_pit_available(ctx: FactorContext):
    # 000001.SZ T 日行 PIT 可得 → 返回 10.0
    val = ctx.point("000001.SZ", "close", T.date())
    assert val == 10.0


def test_point_missing_row_raises_keyerror(ctx: FactorContext):
    # 行不存在（symbol/field/trade_date 组合不在 panel）→ KeyError
    with pytest.raises(KeyError):
        ctx.point("000001.SZ", "close", _dt.date(2099, 12, 31))


def test_point_unknown_field_raises_keyerror(ctx: FactorContext):
    # 字段不在 panel → KeyError（不静默）
    with pytest.raises(KeyError):
        ctx.point("000001.SZ", "nonexistent_field", T.date())


# ---------------------------------------------------------------------------
# 5. snapshot_id 透传
# ---------------------------------------------------------------------------
def test_snapshot_id_recorded(ctx: FactorContext):
    assert ctx.snapshot_id == "snap-20240105-1600"


def test_decision_time_recorded(ctx: FactorContext):
    assert ctx.decision_time == T.replace(hour=16, minute=0)


# ---------------------------------------------------------------------------
# 6. field 未知字段 → KeyError（不静默）
# ---------------------------------------------------------------------------
def test_field_unknown_field_raises_keyerror(ctx: FactorContext):
    with pytest.raises(KeyError):
        ctx.field("nonexistent_field")
