"""每日盘后对账（设计 v0.5 §4.6.4）。

用 Broker 查询结果对账本地订单簿：逐 order_id 比对成交，差异落 audit_event 告警。
- 四类 mismatch：fill_missing_locally / fill_missing_broker / qty_diff / status_diff
- diff_rate = len(mismatches) / max(total_orders, 1)
- passed = diff_rate < threshold
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from quant.data.sqlite_store import SqliteStore

# audit_event.event_type（audit 表字段名为 kind）取值
_AUDIT_KIND = "reconcile_mismatch"


@dataclass
class Mismatch:
    """单条对账差异。

    - kind: 'fill_missing_locally'（broker 有 local 无）
            / 'fill_missing_broker'（local 有 broker 无）
            / 'qty_diff' / 'status_diff'
    - ref_id: 关联的 order_id
    - detail: 人类可读差异描述
    """

    kind: str
    ref_id: str
    detail: str


@dataclass
class ReconcileResult:
    """对账汇总结果。"""

    diff_rate: float
    mismatches: list[Mismatch] = field(default_factory=list)
    passed: bool = False


def reconcile(
    local_fills: dict[str, dict[str, Any]],
    broker_fills: dict[str, dict[str, Any]],
    total_orders: int,
    store: Optional[SqliteStore] = None,
    account_id: str = "",
    threshold: float = 0.001,
) -> ReconcileResult:
    """对账本地订单簿与 Broker 查询结果。

    - local_fills/broker_fills: {order_id: {qty, price, status}}
    - 差异类型见 Mismatch.kind；有差异且 store 提供时落 audit_event
    - diff_rate = mismatches / max(total_orders, 1)，避免零除
    - passed = diff_rate < threshold
    """
    mismatches: list[Mismatch] = []

    local_ids = set(local_fills)
    broker_ids = set(broker_fills)

    # broker 有、local 无
    for oid in broker_ids - local_ids:
        b = broker_fills[oid]
        mismatches.append(
            Mismatch(
                kind="fill_missing_locally",
                ref_id=oid,
                detail=f"broker 有成交 local 无: qty={b.get('qty')}, "
                f"price={b.get('price')}, status={b.get('status')}",
            )
        )

    # local 有、broker 无
    for oid in local_ids - broker_ids:
        l = local_fills[oid]
        mismatches.append(
            Mismatch(
                kind="fill_missing_broker",
                ref_id=oid,
                detail=f"local 有成交 broker 无: qty={l.get('qty')}, "
                f"price={l.get('price')}, status={l.get('status')}",
            )
        )

    # 两边都有：比对 qty / status
    for oid in local_ids & broker_ids:
        l = local_fills[oid]
        b = broker_fills[oid]
        if l.get("qty") != b.get("qty"):
            mismatches.append(
                Mismatch(
                    kind="qty_diff",
                    ref_id=oid,
                    detail=f"qty 不一致: local={l.get('qty')}, broker={b.get('qty')}",
                )
            )
        if l.get("status") != b.get("status"):
            mismatches.append(
                Mismatch(
                    kind="status_diff",
                    ref_id=oid,
                    detail=f"status 不一致: local={l.get('status')}, "
                    f"broker={b.get('status')}",
                )
            )

    diff_rate = len(mismatches) / max(total_orders, 1)
    result = ReconcileResult(
        diff_rate=diff_rate,
        mismatches=mismatches,
        passed=diff_rate < threshold,
    )

    # 差异落 audit_event（§4.6.4 对账告警）
    if store is not None and mismatches:
        for m in mismatches:
            payload = json.dumps(
                {"kind": m.kind, "ref_id": m.ref_id, "detail": m.detail},
                ensure_ascii=False,
            )
            done = store.execute(
                "INSERT INTO audit_event (ts, kind, ref_id, account_id, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (0, _AUDIT_KIND, m.ref_id, account_id, payload),
            )
            done.wait(timeout=5.0)
        store.flush(timeout=5.0)

    return result
