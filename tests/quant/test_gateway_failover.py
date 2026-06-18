from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quant.gateway.base import GatewayHealth
from quant.gateway.failover import FailoverMarketDataGateway, MarketDataUnavailable
from quant.gateway.snapshot import SnapshotMarketDataGateway


def test_failover_subscribe_uses_first_passing_gateway():
    primary = _FakeGateway("qmt", "BLOCKED")
    fallback = _FakeGateway("backup", "PASS")
    gw = FailoverMarketDataGateway([primary, fallback])
    on_bar = MagicMock()

    gw.subscribe(["600519.SH"], "tick", on_bar)

    assert primary.subscribe_calls == []
    assert fallback.subscribe_calls == [(["600519.SH"], "tick", on_bar)]


def test_failover_subscribe_all_blocked_raises_structured_error():
    gw = FailoverMarketDataGateway([
        _FakeGateway("qmt", "BLOCKED"),
        _FakeGateway("backup", "BLOCKED"),
    ])

    with pytest.raises(MarketDataUnavailable) as exc:
        gw.subscribe(["600519.SH"], "tick", MagicMock())

    assert [h.source for h in exc.value.health] == ["qmt", "backup"]
    assert all(h.status == "BLOCKED" for h in exc.value.health)


def test_failover_history_skips_empty_primary():
    primary = _FakeGateway("qmt", "PASS", history_df=pd.DataFrame())
    fallback_df = pd.DataFrame({
        "ts": [datetime(2024, 3, 15, 15)],
        "close": [10.0],
        "available_at": [datetime(2024, 3, 15, 15)],
    })
    fallback = _FakeGateway("backup", "PASS", history_df=fallback_df)
    gw = FailoverMarketDataGateway([primary, fallback])

    df = gw.history(
        "600519.SH",
        "1m",
        datetime(2024, 3, 15, 14, 59),
        datetime(2024, 3, 15, 15),
    )

    assert len(df) == 1
    assert df.iloc[0]["close"] == 10.0


def test_failover_health_reports_degraded_when_no_pass_exists():
    gw = FailoverMarketDataGateway([
        _FakeGateway("qmt", "BLOCKED"),
        _FakeGateway("backup", "DEGRADED"),
    ])

    health = gw.health(["600519.SH"], "tick")

    assert health.source == "backup"
    assert health.status == "DEGRADED"


def test_failover_can_use_snapshot_as_degraded_backup_source():
    snapshot_df = pd.DataFrame({
        "symbol": ["600519.SH"],
        "freq": ["1m"],
        "ts": [datetime(2024, 3, 15, 15)],
        "close": [10.0],
        "volume": [100],
        "available_at": [datetime(2024, 3, 15, 15, 1)],
    })
    gw = FailoverMarketDataGateway([
        _FakeGateway("qmt", "BLOCKED"),
        SnapshotMarketDataGateway(snapshot_df, source="snapshot"),
    ])

    health = gw.health(["600519.SH"], "1m")
    df = gw.history(
        "600519.SH",
        "1m",
        datetime(2024, 3, 15, 14, 59),
        datetime(2024, 3, 15, 15),
    )

    assert health.status == "DEGRADED"
    assert health.source == "snapshot"
    assert len(df) == 1
    assert df.iloc[0]["close"] == 10.0


class _FakeGateway:
    def __init__(
        self,
        source: str,
        status: str,
        *,
        history_df: pd.DataFrame | None = None,
    ) -> None:
        self.source = source
        self.status = status
        self.history_df = history_df if history_df is not None else pd.DataFrame()
        self.subscribe_calls = []

    def health(self, symbols, freq):  # type: ignore[no-untyped-def]
        quality = "REALTIME" if self.status == "PASS" else "UNAVAILABLE"
        if self.status == "DEGRADED":
            quality = "DELAYED"
        return GatewayHealth(
            status=self.status,
            source=self.source,
            quality=quality,
            reason=f"{self.source} {self.status}",
            checked_at=datetime(2024, 1, 1),
        )

    def subscribe(self, symbols, freq, on_bar):  # type: ignore[no-untyped-def]
        self.subscribe_calls.append((symbols, freq, on_bar))

    def history(self, symbol, freq, start, end, as_of=None):  # type: ignore[no-untyped-def]
        return self.history_df

    def bar_at(self, symbol, freq, t, decision_time):  # type: ignore[no-untyped-def]
        return None
