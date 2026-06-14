"""数据快照冻结与可复现测试（设计 v0.5 §3.3.3 / §4.2.2）。

覆盖点：
- create_snapshot：写 factor_snapshot + data_snapshot（as_of_cap 冻结、checksum 确定性）
- snapshot_id 确定性：同 as_of_cap + 同 datasets → 同 id（可复现性可验证）
- snapshot_id 随数据变化：不同 datasets → 不同 id
- load_snapshot：往返读回；未知名 → KeyError
- bind_panel_to_snapshot：过滤 panel 仅留 as_of <= as_of_cap 的行（数据修订裁剪）
- 可复现性（集成）：同 snapshot 同数据二次计算一致；更早 as_of_cap → 结果不同

§3.3.3：数据修订→新 as_of；回测绑定 factor_snapshot_id 冻结 as_of 集合，保证可复现。
snapshot 记录 as_of_cap（允许的最大 as_of 时间戳，毫秒）。

TDD：本文件先于 snapshot.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from quant.data.sqlite_store import SqliteStore
from quant.factor.context import FactorContext
from quant.factor.registry import Factor, FactorRegistry
from quant.factor.snapshot import (
    bind_panel_to_snapshot,
    create_snapshot,
    load_snapshot,
)


# ---------------------------------------------------------------------------
# SqliteStore fixture（tmp_path 隔离，确保用例结束线程回收）
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    s = SqliteStore(str(tmp_path / "snapshot.db"))
    s.start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# 合成数据集
# ---------------------------------------------------------------------------
def _bars_df() -> pd.DataFrame:
    """合成 bars 数据集。"""
    return pd.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "600000.SH"],
            "trade_date": [_dt.date(2024, 1, 4), _dt.date(2024, 1, 5), _dt.date(2024, 1, 4)],
            "close": [10.0, 10.5, 20.0],
        }
    )


# ---------------------------------------------------------------------------
# 1. create + load 往返
# ---------------------------------------------------------------------------
def test_create_and_load_snapshot(store: SqliteStore):
    as_of_cap = 1700000000000  # ms 时间戳
    snap_id = create_snapshot(
        store,
        as_of_cap=as_of_cap,
        datasets={"bars": _bars_df()},
        note="backtest-2024-01",
    )
    assert snap_id  # 非空字符串

    info = load_snapshot(store, snap_id)
    assert info["snapshot_id"] == snap_id
    assert info["as_of_cap"] == as_of_cap
    assert info["note"] == "backtest-2024-01"
    assert "bars" in info["datasets"]
    bar = info["datasets"]["bars"]
    assert bar["checksum"]  # 非空
    assert bar["row_count"] == 3


# ---------------------------------------------------------------------------
# 2. snapshot_id 确定性：同 as_of_cap + 同 datasets → 同 id
# ---------------------------------------------------------------------------
def test_snapshot_id_deterministic(store: SqliteStore):
    as_of_cap = 1700000000000
    id1 = create_snapshot(store, as_of_cap=as_of_cap, datasets={"bars": _bars_df()})
    id2 = create_snapshot(store, as_of_cap=as_of_cap, datasets={"bars": _bars_df()})
    assert id1 == id2  # 同数据同 as_of_cap → 同 snapshot_id（可复现）


# ---------------------------------------------------------------------------
# 3. 不同 datasets → 不同 snapshot_id
# ---------------------------------------------------------------------------
def test_snapshot_id_differs_for_diff_data(store: SqliteStore):
    as_of_cap = 1700000000000
    id_a = create_snapshot(store, as_of_cap=as_of_cap, datasets={"bars": _bars_df()})
    other = _bars_df().copy()
    other.loc[0, "close"] = 999.0
    id_b = create_snapshot(store, as_of_cap=as_of_cap, datasets={"bars": other})
    assert id_a != id_b  # 数据不同 → id 不同


# ---------------------------------------------------------------------------
# 4. load 未知名 → KeyError
# ---------------------------------------------------------------------------
def test_load_unknown_raises(store: SqliteStore):
    with pytest.raises(KeyError):
        load_snapshot(store, "nonexistent")


# ---------------------------------------------------------------------------
# 5. bind_panel_to_snapshot：过滤 as_of <= as_of_cap
# ---------------------------------------------------------------------------
def test_bind_panel_filters_by_as_of_cap():
    # as_of 列为 ms 整数：T、T+100、T+200
    base = 1700000000000
    panel = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "as_of": [base, base + 100, base + 200],
            "close": [10.0, 20.0, 30.0],
        }
    )
    bound = bind_panel_to_snapshot(panel, as_of_cap=base + 100)
    assert set(bound["symbol"]) == {"A", "B"}  # 仅保留 as_of <= cap
    assert "C" not in set(bound["symbol"])


# ---------------------------------------------------------------------------
# 6. 可复现性（集成）：同 snapshot 同数据二次计算一致；更早 as_of_cap → 结果不同
# ---------------------------------------------------------------------------
# 合成 panel 含 as_of（修订戳，ms）+ available_at（PIT，datetime）+ close。
# 两条 close 路径：旧版（as_of 早）与新版（as_of 晚），修订改值。
# - bind 到晚 cap：含两版 → latest 取 trade_date 最大行（此处同 trade_date 多版本
#   由 latest 取 groupby idxmax，为可控此处每 symbol 单一 trade_date，确保确定性）
# - 同 snapshot 二次计算 → R1 == R2
# - bind 到更早 cap（裁掉新版）→ 结果不同
class _LatestClose:
    name = "latest_close"
    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        return ctx.latest("close")


def _repro_panel() -> pd.DataFrame:
    """3 symbol 的 close；600000.SH 有修订版（as_of 晚、trade_date 更后、值变）。

    修订（§3.3.3）= 数据源后补一行更新（as_of 更晚）；latest 按 trade_date 取最大，
    故含修订版时取新 trade_date 的值，被裁掉时回退旧值。
    """
    base_as_of = 1700000000000
    return pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": _dt.date(2024, 1, 5),
                "available_at": _dt.datetime(2024, 1, 5, 16, 0),
                "as_of": base_as_of,
                "close": 10.0,
            },
            # 600000.SH 旧版：trade_date 1-4，close 20.0
            {
                "symbol": "600000.SH",
                "trade_date": _dt.date(2024, 1, 4),
                "available_at": _dt.datetime(2024, 1, 5, 16, 0),
                "as_of": base_as_of,
                "close": 20.0,
            },
            # 600000.SH 修订版：as_of 更晚、补一行 trade_date 1-5、close 21.5
            {
                "symbol": "600000.SH",
                "trade_date": _dt.date(2024, 1, 5),
                "available_at": _dt.datetime(2024, 1, 5, 16, 0),
                "as_of": base_as_of + 100_000,
                "close": 21.5,
            },
            {
                "symbol": "300001.SZ",
                "trade_date": _dt.date(2024, 1, 5),
                "available_at": _dt.datetime(2024, 1, 5, 16, 0),
                "as_of": base_as_of,
                "close": 30.0,
            },
        ]
    )


def test_reproducibility_via_registry(store: SqliteStore):
    base_as_of = 1700000000000
    panel_full = _repro_panel()
    # 冻结到包含修订版（cap >= 最新 as_of）
    late_cap = base_as_of + 200_000
    create_snapshot(store, as_of_cap=late_cap, datasets={"panel": panel_full})

    reg = FactorRegistry()
    reg.register(_LatestClose())

    def _compute() -> pd.DataFrame:
        bound = bind_panel_to_snapshot(panel_full, as_of_cap=late_cap)
        return reg.compute_panel(
            names=["latest_close"],
            t=_dt.datetime(2024, 1, 5, 17, 0),
            universe=["000001.SZ", "600000.SH", "300001.SZ"],
            snapshot_id="snap-late",
            panel=bound,
        )

    r1 = _compute()
    r2 = _compute()
    pd.testing.assert_frame_equal(r1, r2)  # 同 snapshot 同数据二次计算一致
    # 含修订版：600000.SH latest 取 trade_date 更大的修订行 → 21.5
    assert r1.loc["600000.SH", "latest_close"] == 21.5

    # 更早 as_of_cap：裁掉 600000.SH 修订版（as_of 晚），latest 回退旧版 → 结果不同
    early_cap = base_as_of
    bound_early = bind_panel_to_snapshot(panel_full, as_of_cap=early_cap)
    r_early = reg.compute_panel(
        names=["latest_close"],
        t=_dt.datetime(2024, 1, 5, 17, 0),
        universe=["000001.SZ", "600000.SH", "300001.SZ"],
        snapshot_id="snap-early",
        panel=bound_early,
    )
    assert not r1.equals(r_early)  # 数据被截断 → 结果不同
    # 600000.SH 在更早 cap 下回退旧值 20.0
    assert r_early.loc["600000.SH", "latest_close"] == 20.0
