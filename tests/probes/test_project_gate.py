from probes.network_gate import NetworkCheck, NetworkGateResult
from probes.project_gate import ProjectGateResult, run_project_gate
from probes.qmt_live import QmtLiveProbeResult


def test_project_gate_blocks_when_qmt_market_data_is_unhealthy() -> None:
    result = run_project_gate(
        qmt_runner=lambda: QmtLiveProbeResult(
            status="pass",
            reason="xtquant readonly probe passed",
            checks={
                "xtquant_import": True,
                "market_data_read": True,
                "market_data_health": False,
                "trader_readonly_handshake": True,
            },
        ),
        network_runner=lambda: NetworkGateResult([
            NetworkCheck("baostock_daily", "PASS", True, "rows=5"),
            NetworkCheck("llm_api", "PASS", True, "non_empty_response"),
        ]),
    )

    assert result.status == "BLOCKED"
    assert result.checks["qmt_trader"] == "PASS"
    assert result.checks["qmt_market_data_health"] == "BLOCKED"
    assert result.checks["live_readiness"] == "BLOCKED"
    assert "QMT realtime market data is unavailable" in result.reason


def test_project_gate_passes_when_required_qmt_and_network_checks_pass() -> None:
    result = run_project_gate(
        qmt_runner=lambda: QmtLiveProbeResult(
            status="pass",
            reason="xtquant readonly probe passed",
            checks={
                "xtquant_import": True,
                "market_data_read": True,
                "market_data_health": True,
                "trader_readonly_handshake": True,
            },
        ),
        network_runner=lambda: NetworkGateResult([
            NetworkCheck("akshare_daily", "BLOCKED", False, "proxy"),
            NetworkCheck("baostock_daily", "PASS", True, "rows=5"),
            NetworkCheck("llm_api", "PASS", True, "non_empty_response"),
        ]),
    )

    assert result.status == "PASS"
    assert result.checks["live_readiness"] == "PASS"
    assert result.reason == "project gate passed"


def test_project_gate_blocks_when_required_network_check_blocks() -> None:
    result = run_project_gate(
        qmt_runner=lambda: QmtLiveProbeResult(
            status="pass",
            reason="xtquant readonly probe passed",
            checks={
                "xtquant_import": True,
                "market_data_read": True,
                "market_data_health": True,
                "trader_readonly_handshake": True,
            },
        ),
        network_runner=lambda: NetworkGateResult([
            NetworkCheck("llm_api", "BLOCKED", True, "empty response"),
        ]),
    )

    assert result.status == "BLOCKED"
    assert "required network checks are blocked: llm_api" in result.reason


def test_project_gate_lines_report_summary_without_secrets() -> None:
    result = ProjectGateResult(
        status="BLOCKED",
        reason="token=secret should be hidden",
        checks={"qmt_trader": "PASS"},
        network=NetworkGateResult([
            NetworkCheck("llm_api", "BLOCKED", True, "api_key=secret-token"),
        ]),
    )

    text = "\n".join(result.lines())

    assert "secret" not in text
    assert "token=***" in text
    assert "api_key=***" in text
    assert "qmt_trader=PASS" in text
