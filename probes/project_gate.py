"""Project-level readiness gate.

This module aggregates local QMT readiness and external network readiness into
one operator-facing result. It is intentionally read-only: the QMT probe does
not place or cancel orders, and the network gate only performs smoke checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Callable, Iterable, Literal

from probes.network_gate import NetworkGateResult, overall_status, run_network_gate
from probes.qmt_live import load_config, run_readonly_probe
from quant.execution.live_readiness import evaluate_live_readiness
from quant.gateway.base import GatewayHealth

ProjectStatus = Literal["PASS", "BLOCKED"]


@dataclass(frozen=True)
class ProjectGateResult:
    status: ProjectStatus
    reason: str
    checks: dict[str, ProjectStatus] = field(default_factory=dict)
    network: NetworkGateResult | None = None

    def lines(self) -> Iterable[str]:
        yield f"status={self.status}"
        yield f"reason={_redact(self.reason)}"
        for name, status in self.checks.items():
            yield f"{name}={status}"
        if self.network is not None:
            yield from self.network.lines()


def run_project_gate(
    *,
    qmt_runner: Callable[[], object] | None = None,
    network_runner: Callable[[], NetworkGateResult] = run_network_gate,
) -> ProjectGateResult:
    """Run the full project gate and return a structured readiness result."""
    qmt_result = (
        qmt_runner()
        if qmt_runner is not None
        else run_readonly_probe(load_config())
    )
    qmt_checks = getattr(qmt_result, "checks", {})

    checks: dict[str, ProjectStatus] = {
        "qmt_xtquant_import": _bool_status(qmt_checks.get("xtquant_import")),
        "qmt_market_data_read": _bool_status(qmt_checks.get("market_data_read")),
        "qmt_market_data_health": _bool_status(qmt_checks.get("market_data_health")),
        "qmt_trader": _bool_status(qmt_checks.get("trader_readonly_handshake")),
    }
    live_readiness = evaluate_live_readiness(
        _ProbeMarketGateway(qmt_checks.get("market_data_health") is True),
        symbols=[getattr(load_config(), "symbol", "600519.SH")],
        freq="tick",
        broker=_ProbeBroker(qmt_checks.get("trader_readonly_handshake") is True),
    )
    checks["live_readiness"] = live_readiness.status

    network = network_runner()
    blocked_reasons: list[str] = []

    if getattr(qmt_result, "status", None) != "pass":
        reason = getattr(qmt_result, "reason", "unknown")
        blocked_reasons.append(f"QMT readonly probe blocked: {reason}")
    if checks["qmt_trader"] != "PASS":
        blocked_reasons.append("QMT trader readonly handshake is unavailable")
    if checks["qmt_market_data_health"] != "PASS":
        blocked_reasons.append("QMT realtime market data is unavailable")
    if live_readiness.status != "PASS":
        blocked_reasons.append(f"live readiness blocked: {live_readiness.reason}")

    required_blocked = [
        check.name for check in network.checks
        if check.required and check.status != "PASS"
    ]
    if overall_status(network) != "PASS":
        blocked_reasons.append(
            "required network checks are blocked: " + ", ".join(required_blocked)
        )

    if blocked_reasons:
        return ProjectGateResult(
            status="BLOCKED",
            reason="; ".join(blocked_reasons),
            checks=checks,
            network=network,
        )

    return ProjectGateResult(
        status="PASS",
        reason="project gate passed",
        checks=checks,
        network=network,
    )


def _bool_status(value: object) -> ProjectStatus:
    return "PASS" if value is True else "BLOCKED"


class _ProbeMarketGateway:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    def health(self, symbols: list[str], freq: str) -> GatewayHealth:
        if self._healthy:
            return GatewayHealth(
                status="PASS",
                source="qmt_live_probe",
                quality="REALTIME",
                reason="probe market_data_health passed",
                checked_at=datetime.now(),
            )
        return GatewayHealth(
            status="BLOCKED",
            source="qmt_live_probe",
            quality="UNAVAILABLE",
            reason="probe market_data_health blocked",
            checked_at=datetime.now(),
        )


class _ProbeBroker:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    def account(self) -> dict:
        if not self._healthy:
            raise RuntimeError("probe trader readonly handshake blocked")
        return {}


def _redact(text: str) -> str:
    text = re.sub(r"(?i)(api[_-]?key=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(token=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(password=)[^\s,;]+", r"\1***", text)
    return text


def main() -> None:
    result = run_project_gate()
    for line in result.lines():
        print(line)


if __name__ == "__main__":
    main()
