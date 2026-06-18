import subprocess

import probes.full_gate as full_gate_module
from probes.full_gate import CommandCheck, FullGateResult, run_full_gate
from probes.network_gate import NetworkGateResult
from probes.project_gate import ProjectGateResult


def test_full_gate_passes_when_regression_and_project_pass() -> None:
    result = run_full_gate(
        command_runner=lambda check: CommandCheck(
            name=check.name,
            status="PASS",
            command=check.command,
            reason="ok",
        ),
        project_runner=lambda: ProjectGateResult(
            status="PASS",
            reason="project gate passed",
            checks={"live_readiness": "PASS"},
            network=NetworkGateResult([]),
        ),
    )

    assert result.status == "PASS"
    assert [check.status for check in result.regression] == ["PASS", "PASS", "PASS"]
    assert result.project.status == "PASS"


def test_full_gate_blocks_when_regression_command_fails() -> None:
    def runner(check):  # type: ignore[no-untyped-def]
        status = "BLOCKED" if check.name == "quant_non_network" else "PASS"
        return CommandCheck(
            name=check.name,
            status=status,
            command=check.command,
            reason="pytest failed" if status == "BLOCKED" else "ok",
        )

    result = run_full_gate(
        command_runner=runner,
        project_runner=lambda: ProjectGateResult(
            status="PASS",
            reason="project gate passed",
            checks={},
            network=NetworkGateResult([]),
        ),
    )

    assert result.status == "BLOCKED"
    assert "quant_non_network" in result.reason


def test_full_gate_blocks_when_project_gate_blocks() -> None:
    result = run_full_gate(
        command_runner=lambda check: CommandCheck(
            name=check.name,
            status="PASS",
            command=check.command,
            reason="ok",
        ),
        project_runner=lambda: ProjectGateResult(
            status="BLOCKED",
            reason="QMT realtime market data is unavailable",
            checks={"live_readiness": "BLOCKED"},
            network=NetworkGateResult([]),
        ),
    )

    assert result.status == "BLOCKED"
    assert result.reason == "project gate blocked"


def test_full_gate_lines_redact_sensitive_output() -> None:
    result = FullGateResult(
        status="BLOCKED",
        reason="token=secret",
        regression=[
            CommandCheck(
                name="quant",
                status="BLOCKED",
                command=["pytest"],
                reason="api_key=secret-token",
            ),
        ],
        project=ProjectGateResult(
            status="BLOCKED",
            reason="password=secret",
            checks={},
            network=NetworkGateResult([]),
        ),
    )

    text = "\n".join(result.lines())

    assert "secret" not in text
    assert "token=***" in text
    assert "api_key=***" in text
    assert "password=***" in text


def test_full_gate_command_timeout_is_structured_blocked(monkeypatch) -> None:
    def timeout_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=300)

    monkeypatch.setattr(full_gate_module.subprocess, "run", timeout_run)

    result = run_full_gate(
        checks=[full_gate_module.CommandSpec("slow_check", ["pytest"])],
        project_runner=lambda: ProjectGateResult(
            status="PASS",
            reason="project gate passed",
            checks={},
            network=NetworkGateResult([]),
        ),
    )

    assert result.status == "BLOCKED"
    assert result.regression[0].status == "BLOCKED"
    assert "timed out after 300s" in result.regression[0].reason
