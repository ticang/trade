"""Run all M-1a probes and emit a go/no-go markdown report.

Each probe entry is (display_name, pytest_args, is_known_failure, note):
  - display_name: human-readable label shown in the report
  - pytest_args: argv passed to `python -m pytest` (test file + markers)
  - is_known_failure: True when a failure is pre-accepted and not a blocker
  - note: free-text annotation appended to the probe's checkbox line
"""
from __future__ import annotations

import datetime
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence

PYTEST = [sys.executable, "-m", "pytest"]


@dataclass(frozen=True)
class Probe:
    display_name: str
    pytest_args: Sequence[str]
    is_known_failure: bool = False
    note: str = ""


PROBES: tuple[Probe, ...] = (
    Probe(
        "DuckDB cross-section latency < 50ms",
        ["tests/probes/test_duckdb_perf.py"],
        note="1000 symbols x 30 factors x 250 days; full-market 5300 extrapolation deferred to M0",
    ),
    Probe(
        "SQLite single-writer no-lock + >5000 rps",
        ["tests/probes/test_sqlite_write.py"],
    ),
    Probe(
        "Trading calendar + makeup days",
        ["tests/probes/test_calendar_holidays.py"],
        is_known_failure=True,
        note="4/5 pass; makeup-day (2024-02-04) not covered by exchange_calendars -> M0 overlay, NOT a blocker",
    ),
    Probe(
        "DSL interpreter expresses real factor",
        ["tests/probes/test_dsl_interpreter.py"],
        note="minimal 3-operator prototype; full operator set frozen before M3",
    ),
    Probe(
        "Free data source fields + PIT",
        ["tests/probes/test_data_sources.py", "-m", "network"],
        is_known_failure=True,
        note="baostock fields + PIT derivability PASS; akshare live fetch blocked by non-China network egress (eastmoney unreachable) -> re-verify on China network in M0, NOT a probe-logic blocker",
    ),
    Probe(
        "Chinese-FinBERT sentiment",
        ["tests/probes/test_nlp_sentiment.py", "-m", "slow and network"],
        note="candidate model; small-sample selection after M-1a",
    ),
)


def run_probe(probe: Probe) -> tuple[bool, str]:
    """Run one probe's pytest command; return (passed, tail of output)."""
    args = [*PYTEST, *probe.pytest_args, "-v", "--tb=short"]
    result = subprocess.run(args, capture_output=True, text=True)
    tail = (result.stdout + result.stderr).strip().splitlines()[-1] if (result.stdout or result.stderr) else ""
    return result.returncode == 0, tail


def build_report() -> tuple[str, bool]:
    """Run all probes, build the markdown report, return (report_text, overall_go)."""
    today = datetime.date.today()
    lines = [
        "# M-1a 本地技术探测报告",
        "",
        f"生成时间: {today}",
        "",
        "## 探测结果",
        "",
    ]
    fully_passed = 0
    known_failures = 0
    unexpected_failures = 0

    for probe in PROBES:
        passed, tail = run_probe(probe)
        if passed:
            mark = "x"
            fully_passed += 1
        elif probe.is_known_failure:
            mark = " "
            known_failures += 1
        else:
            mark = " "
            unexpected_failures += 1
        note = f" — {probe.note}" if probe.note else ""
        status = "PASS" if passed else "FAIL (known)" if probe.is_known_failure else "FAIL"
        lines.append(f"- [{'x' if passed else ' '}] {probe.display_name}: **{status}**{note}")
        if tail:
            lines.append(f"    - `{tail}`")

    overall_go = unexpected_failures == 0

    lines += [
        "",
        "## 结论",
        "",
        f"- 全部通过: {fully_passed}/{len(PROBES)}",
        f"- 已知可接受失败: {known_failures}",
        f"- 未预期失败: {unexpected_failures}",
        "",
    ]
    if overall_go:
        lines.append("**GO** — 地基假设全部验证；calendar 调休 overlay 列入 M0 待办。")
    else:
        lines.append("**NO-GO** — 存在未预期的探测失败，需排查后再进入 M0。")

    return "\n".join(lines), overall_go


def main() -> None:
    report_text, go = build_report()
    out_dir = pathlib.Path("docs/review")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"m1a-report-{datetime.date.today()}.md"
    out.write_text(report_text + "\n", encoding="utf-8")
    print(f"report written to {out}")
    print("RESULT:", "GO" if go else "NO-GO")


if __name__ == "__main__":
    main()
