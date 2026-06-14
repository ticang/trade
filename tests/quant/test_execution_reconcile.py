"""每日对账测试（设计 v0.5 §4.6.4）。

覆盖：
- 四类 mismatch：fill_missing_locally / fill_missing_broker / qty_diff / status_diff
- diff_rate = mismatches / max(total_orders, 1)
- passed = diff_rate < threshold
- store 提供时落 audit_event（kind='reconcile_mismatch'）
- total_orders=0 不崩（diff_rate=0）

TDD：本文件先于 reconcile.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.execution.reconcile import (
    Mismatch,
    ReconcileResult,
    reconcile,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    s = SqliteStore(str(tmp_path / "reconcile.db"))
    s.start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# 无差异
# ---------------------------------------------------------------------------


def test_reconcile_no_diff():
    """local 与 broker 完全一致：无 mismatch，diff_rate=0，passed=True。"""
    fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    result = reconcile(fills, fills, total_orders=1)
    assert result.mismatches == []
    assert result.diff_rate == 0.0
    assert result.passed is True


# ---------------------------------------------------------------------------
# 四类 mismatch
# ---------------------------------------------------------------------------


def test_fill_missing_locally():
    """broker 有、local 无 → fill_missing_locally。"""
    broker_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    result = reconcile({}, broker_fills, total_orders=1)
    assert len(result.mismatches) == 1
    m = result.mismatches[0]
    assert m.kind == "fill_missing_locally"
    assert m.ref_id == "o1"


def test_fill_missing_broker():
    """local 有、broker 无 → fill_missing_broker。"""
    local_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    result = reconcile(local_fills, {}, total_orders=1)
    assert len(result.mismatches) == 1
    m = result.mismatches[0]
    assert m.kind == "fill_missing_broker"
    assert m.ref_id == "o1"


def test_qty_diff():
    """两边都有但 qty 不等 → qty_diff。"""
    local_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    broker_fills = {"o1": {"qty": 99, "price": 10.0, "status": "filled"}}
    result = reconcile(local_fills, broker_fills, total_orders=1)
    assert len(result.mismatches) == 1
    assert result.mismatches[0].kind == "qty_diff"
    assert result.mismatches[0].ref_id == "o1"


def test_status_diff():
    """两边都有但 status 不等 → status_diff。"""
    local_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    broker_fills = {"o1": {"qty": 100, "price": 10.0, "status": "partial_filled"}}
    result = reconcile(local_fills, broker_fills, total_orders=1)
    assert len(result.mismatches) == 1
    assert result.mismatches[0].kind == "status_diff"
    assert result.mismatches[0].ref_id == "o1"


# ---------------------------------------------------------------------------
# diff_rate 与阈值
# ---------------------------------------------------------------------------


def test_diff_rate_threshold():
    """1/100=0.01 > 0.001 → passed=False；0/100 → passed=True。"""
    # 1 个 mismatch / 100 订单
    broker_fills = {"o1": {"qty": 1, "price": 1.0, "status": "filled"}}
    result_bad = reconcile({}, broker_fills, total_orders=100, threshold=0.001)
    assert result_bad.diff_rate == pytest.approx(0.01)
    assert result_bad.passed is False

    # 0 mismatch / 100 订单
    fills = {"o1": {"qty": 1, "price": 1.0, "status": "filled"}}
    result_good = reconcile(fills, fills, total_orders=100, threshold=0.001)
    assert result_good.diff_rate == 0.0
    assert result_good.passed is True


# ---------------------------------------------------------------------------
# audit 落库
# ---------------------------------------------------------------------------


def test_audit_logged(store):
    """有 mismatch 且 store 提供 → audit_event 落对应行。"""
    broker_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    result = reconcile(
        {},
        broker_fills,
        total_orders=1,
        store=store,
        account_id="acct-1",
    )
    assert len(result.mismatches) == 1

    rows = store.query_all(
        "SELECT kind, ref_id, account_id, payload "
        "FROM audit_event WHERE kind = 'reconcile_mismatch'"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["ref_id"] == "o1"
    assert row["account_id"] == "acct-1"
    payload = json.loads(row["payload"])
    assert payload["kind"] == "fill_missing_locally"
    assert payload["ref_id"] == "o1"
    assert "detail" in payload


def test_audit_not_written_when_no_store():
    """store=None 时不应崩；mismatch 仍返回。"""
    broker_fills = {"o1": {"qty": 100, "price": 10.0, "status": "filled"}}
    result = reconcile({}, broker_fills, total_orders=1)
    assert len(result.mismatches) == 1


# ---------------------------------------------------------------------------
# 边界：total_orders=0
# ---------------------------------------------------------------------------


def test_total_orders_zero_safe():
    """total_orders=0 不崩（max(0,1)=1，diff_rate=0/1=0）。"""
    result = reconcile({}, {}, total_orders=0)
    assert result.mismatches == []
    assert result.diff_rate == 0.0
    assert result.passed is True
