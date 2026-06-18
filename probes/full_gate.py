"""Full local + external project gate.

This CLI gives operators one command for the current release gate:
deterministic non-network regression first, then the QMT/network project gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
import sys
from typing import Callable, Iterable, Literal

from probes.project_gate import ProjectGateResult, run_project_gate

GateStatus = Literal["PASS", "BLOCKED"]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: list[str]


@dataclass(frozen=True)
class CommandCheck:
    name: str
    status: GateStatus
    command: list[str]
    reason: str


@dataclass(frozen=True)
class FullGateResult:
    status: GateStatus
    reason: str
    regression: list[CommandCheck]
    project: ProjectGateResult

    def lines(self) -> Iterable[str]:
        yield f"status={self.status}"
        yield f"reason={_redact(self.reason)}"
        for check in self.regression:
            command = " ".join(check.command)
            yield (
                f"{check.name}={check.status} "
                f"command={command} reason={_redact(_shorten(check.reason))}"
            )
        yield "project_gate:"
        for line in self.project.lines():
            yield "  " + line


def default_regression_checks() -> list[CommandSpec]:
    return [
        CommandSpec(
            "probes_non_network",
            [sys.executable, "-m", "pytest", "tests\\probes", "-m", "not network", "-q"],
        ),
        CommandSpec(
            "quant_non_network",
            [sys.executable, "-m", "pytest", "tests\\quant", "-m", "not network", "-q"],
        ),
        CommandSpec("git_diff_check", ["git", "diff", "--check"]),
    ]


def run_full_gate(
    *,
    checks: list[CommandSpec] | None = None,
    command_runner: Callable[[CommandSpec], CommandCheck] | None = None,
    project_runner: Callable[[], ProjectGateResult] = run_project_gate,
) -> FullGateResult:
    runner = command_runner or _run_command
    regression = [runner(check) for check in (checks or default_regression_checks())]
    project = project_runner()

    blocked_regression = [check.name for check in regression if check.status != "PASS"]
    if blocked_regression:
        return FullGateResult(
            status="BLOCKED",
            reason="regression checks blocked: " + ", ".join(blocked_regression),
            regression=regression,
            project=project,
        )
    if project.status != "PASS":
        return FullGateResult(
            status="BLOCKED",
            reason="project gate blocked",
            regression=regression,
            project=project,
        )
    return FullGateResult(
        status="PASS",
        reason="full gate passed",
        regression=regression,
        project=project,
    )


def _run_command(check: CommandSpec) -> CommandCheck:
    try:
        completed = subprocess.run(
            check.command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandCheck(
            name=check.name,
            status="BLOCKED",
            command=check.command,
            reason=f"command timed out after {exc.timeout}s",
        )
    output = "\n".join(
        part.strip()
        for part in [completed.stdout, completed.stderr]
        if part.strip()
    )
    status: GateStatus = "PASS" if completed.returncode == 0 else "BLOCKED"
    reason = output or f"exit_code={completed.returncode}"
    return CommandCheck(
        name=check.name,
        status=status,
        command=check.command,
        reason=reason,
    )


def _redact(text: str) -> str:
    text = re.sub(r"(?i)(api[_-]?key=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(token=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(password=)[^\s,;]+", r"\1***", text)
    return text


def _shorten(text: str, *, limit: int = 220) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def main() -> None:
    result = run_full_gate()
    for line in result.lines():
        print(line)
    raise SystemExit(0 if result.status == "PASS" else 1)


if __name__ == "__main__":
    main()
