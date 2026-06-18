from probes.network_gate import NetworkCheck, NetworkGateResult, overall_status, shorten_reason


def test_overall_status_passes_when_all_required_pass():
    result = NetworkGateResult([
        NetworkCheck(name="baostock", status="PASS", required=True, reason="ok"),
        NetworkCheck(name="akshare", status="BLOCKED", required=False, reason="proxy"),
    ])

    assert overall_status(result) == "PASS"


def test_overall_status_blocks_when_required_check_blocked():
    result = NetworkGateResult([
        NetworkCheck(name="llm", status="BLOCKED", required=True, reason="empty"),
    ])

    assert overall_status(result) == "BLOCKED"


def test_network_gate_result_lines_hide_sensitive_values():
    result = NetworkGateResult([
        NetworkCheck(
            name="llm",
            status="PASS",
            required=True,
            reason="api_key=secret-token ok",
        ),
    ])

    text = "\n".join(result.lines())

    assert "secret-token" not in text
    assert "api_key=***" in text


def test_shorten_reason_keeps_proxy_failure_readable():
    reason = (
        "ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', "
        "port=443): Max retries exceeded with url: /very/long/path"
    )

    got = shorten_reason(reason, limit=60)

    assert got.startswith("ProxyError")
    assert len(got) <= 63
