"""Live trading readiness guard.

This guard is the execution-side counterpart of market-data health checks. It
keeps automatic live trading blocked unless the selected market data source is
explicitly PASS/REALTIME and the broker can answer a readonly account check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from quant.gateway.base import GatewayHealth

ReadinessStatus = Literal["PASS", "BLOCKED"]

__all__ = [
    "LiveReadiness",
    "LiveReadinessError",
    "assert_live_trading_ready",
    "evaluate_live_readiness",
]


@dataclass(frozen=True)
class LiveReadiness:
    status: ReadinessStatus
    reason: str
    market_health: GatewayHealth
    broker_status: ReadinessStatus


class LiveReadinessError(RuntimeError):
    """Raised when a caller attempts to enter live trading without readiness."""

    def __init__(self, result: LiveReadiness) -> None:
        super().__init__(result.reason)
        self.result = result


def evaluate_live_readiness(
    market_data: Any,
    *,
    symbols: list[str],
    freq: str,
    broker: Any | None = None,
) -> LiveReadiness:
    """Evaluate whether automatic live trading may run.

    Rules:
    - Market data must expose health(), and health must be PASS/REALTIME.
    - DEGRADED or HISTORICAL data is valid for shadow/simulation only.
    - Broker, when supplied, must answer a readonly account() smoke check.
    """
    health_fn = getattr(market_data, "health", None)
    if not callable(health_fn):
        return _blocked(
            _unknown_health(type(market_data).__name__),
            "market data gateway does not expose health()",
            broker_status="BLOCKED",
        )

    market_health = health_fn(symbols, freq)
    broker_status, broker_reason = _broker_readonly_status(broker)
    reasons: list[str] = []

    if market_health.status != "PASS" or market_health.quality != "REALTIME":
        reasons.append(
            "live trading requires PASS/REALTIME market data; "
            f"got {market_health.status}/{market_health.quality} "
            f"from {market_health.source}: {market_health.reason}"
        )
    if broker_status != "PASS":
        reasons.append(broker_reason)

    if reasons:
        return LiveReadiness(
            status="BLOCKED",
            reason="; ".join(reasons),
            market_health=market_health,
            broker_status=broker_status,
        )

    return LiveReadiness(
        status="PASS",
        reason="live trading readiness passed",
        market_health=market_health,
        broker_status="PASS",
    )


def assert_live_trading_ready(
    market_data: Any,
    *,
    symbols: list[str],
    freq: str,
    broker: Any | None = None,
) -> LiveReadiness:
    result = evaluate_live_readiness(
        market_data,
        symbols=symbols,
        freq=freq,
        broker=broker,
    )
    if result.status != "PASS":
        raise LiveReadinessError(result)
    return result


def _broker_readonly_status(broker: Any | None) -> tuple[ReadinessStatus, str]:
    if broker is None:
        return "PASS", "broker check skipped"
    account = getattr(broker, "account", None)
    if not callable(account):
        return "BLOCKED", "broker does not expose account() readonly check"
    try:
        account()
    except Exception as exc:  # noqa: BLE001 - readiness guard reports boundary failures.
        return (
            "BLOCKED",
            f"broker readonly account check failed: {type(exc).__name__}: {exc}",
        )
    return "PASS", "broker readonly account check passed"


def _blocked(
    health: GatewayHealth,
    reason: str,
    *,
    broker_status: ReadinessStatus,
) -> LiveReadiness:
    return LiveReadiness(
        status="BLOCKED",
        reason=reason,
        market_health=health,
        broker_status=broker_status,
    )


def _unknown_health(source: str) -> GatewayHealth:
    return GatewayHealth(
        status="BLOCKED",
        source=source,
        quality="UNAVAILABLE",
        reason="gateway does not expose health()",
        checked_at=datetime.now(),
    )
