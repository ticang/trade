"""External network health gate.

This probe separates external-service health from deterministic local tests.
It avoids turning a proxy/API outage into an ambiguous code-regression signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Callable, Iterable, Literal

from probes.data_sources import fetch_akshare_daily, fetch_baostock_daily
from quant.llm.client import LLMClient

Status = Literal["PASS", "BLOCKED"]


@dataclass(frozen=True)
class NetworkCheck:
    name: str
    status: Status
    required: bool
    reason: str


@dataclass(frozen=True)
class NetworkGateResult:
    checks: list[NetworkCheck]

    def lines(self) -> Iterable[str]:
        for check in self.checks:
            required = "required" if check.required else "optional"
            yield (
                f"{check.name}={check.status} ({required}) "
                f"reason={shorten_reason(_redact(check.reason))}"
            )


def overall_status(result: NetworkGateResult) -> Status:
    for check in result.checks:
        if check.required and check.status != "PASS":
            return "BLOCKED"
    return "PASS"


def run_network_gate() -> NetworkGateResult:
    return NetworkGateResult([
        _run_check("akshare_daily", required=False, fn=_check_akshare),
        _run_check("baostock_daily", required=True, fn=_check_baostock),
        _run_check("llm_api", required=True, fn=_check_llm),
    ])


def _run_check(
    name: str,
    *,
    required: bool,
    fn: Callable[[], str],
) -> NetworkCheck:
    try:
        reason = fn()
    except Exception as exc:  # noqa: BLE001 - probe reports external failures.
        return NetworkCheck(
            name=name,
            status="BLOCKED",
            required=required,
            reason=f"{type(exc).__name__}: {exc}",
        )
    return NetworkCheck(name=name, status="PASS", required=required, reason=reason)


def _check_akshare() -> str:
    df = fetch_akshare_daily(
        "000001",
        start=date(2024, 3, 1),
        end=date(2024, 3, 7),
        retries=1,
        timeout=3.0,
    )
    return f"rows={len(df)}"


def _check_baostock() -> str:
    df = fetch_baostock_daily(
        "sz.000001",
        start=date(2024, 3, 1),
        end=date(2024, 3, 7),
    )
    return f"rows={len(df)}"


def _check_llm() -> str:
    client = LLMClient()
    out = client.complete(
        [{"role": "user", "content": "只输出一个词：连通"}],
        max_tokens=16,
    )
    if not out:
        raise RuntimeError("empty LLM response")
    return "non_empty_response"


def _redact(text: str) -> str:
    text = re.sub(r"(?i)(api[_-]?key=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(token=)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(password=)[^\s,;]+", r"\1***", text)
    return text


def shorten_reason(text: str, *, limit: int = 180) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def main() -> None:
    result = run_network_gate()
    print(f"status={overall_status(result)}")
    for line in result.lines():
        print(line)


if __name__ == "__main__":
    main()
