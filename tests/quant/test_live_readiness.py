from datetime import datetime

import pytest

from quant.execution.live_readiness import (
    LiveReadinessError,
    assert_live_trading_ready,
    evaluate_live_readiness,
)
from quant.gateway.base import GatewayHealth


def test_live_readiness_passes_only_for_realtime_market_and_broker() -> None:
    result = evaluate_live_readiness(
        _Gateway("PASS", "REALTIME"),
        symbols=["600519.SH"],
        freq="tick",
        broker=_Broker(account_result={"cash": 1000}),
    )

    assert result.status == "PASS"
    assert result.market_health.status == "PASS"
    assert result.broker_status == "PASS"


def test_live_readiness_blocks_degraded_market_data() -> None:
    result = evaluate_live_readiness(
        _Gateway("DEGRADED", "DELAYED"),
        symbols=["600519.SH"],
        freq="tick",
        broker=_Broker(account_result={"cash": 1000}),
    )

    assert result.status == "BLOCKED"
    assert "requires PASS/REALTIME market data" in result.reason


def test_live_readiness_blocks_gateway_without_health_contract() -> None:
    result = evaluate_live_readiness(
        _LegacyGateway(),
        symbols=["600519.SH"],
        freq="tick",
        broker=_Broker(account_result={"cash": 1000}),
    )

    assert result.status == "BLOCKED"
    assert "does not expose health()" in result.reason


def test_live_readiness_blocks_when_broker_smoke_fails() -> None:
    result = evaluate_live_readiness(
        _Gateway("PASS", "REALTIME"),
        symbols=["600519.SH"],
        freq="tick",
        broker=_Broker(error=RuntimeError("offline")),
    )

    assert result.status == "BLOCKED"
    assert result.broker_status == "BLOCKED"
    assert "broker readonly account check failed" in result.reason


def test_assert_live_trading_ready_raises_structured_error() -> None:
    with pytest.raises(LiveReadinessError) as exc:
        assert_live_trading_ready(
            _Gateway("BLOCKED", "UNAVAILABLE"),
            symbols=["600519.SH"],
            freq="tick",
            broker=_Broker(account_result={"cash": 1000}),
        )

    assert exc.value.result.status == "BLOCKED"
    assert "requires PASS/REALTIME market data" in str(exc.value)


class _Gateway:
    def __init__(self, status: str, quality: str) -> None:
        self.status = status
        self.quality = quality

    def health(self, symbols, freq):  # type: ignore[no-untyped-def]
        return GatewayHealth(
            status=self.status,
            source="test",
            quality=self.quality,
            reason=f"{self.status}/{self.quality}",
            checked_at=datetime(2024, 1, 1),
        )


class _LegacyGateway:
    pass


class _Broker:
    def __init__(self, account_result=None, error: Exception | None = None) -> None:
        self.account_result = account_result
        self.error = error

    def account(self):  # type: ignore[no-untyped-def]
        if self.error is not None:
            raise self.error
        return self.account_result
