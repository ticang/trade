from __future__ import annotations

import types

from probes.qmt_live import QmtLiveProbeConfig, load_config, run_readonly_probe


def test_load_config_ignores_secret_values() -> None:
    config = load_config(
        {
            "QMT_ACCOUNT": "acct1",
            "QMT_PASSWORD": "should-not-appear",
            "QMT_TOKEN": "should-not-appear",
            "QMT_USERDATA_PATH": r"C:\qmt\userdata_mini",
            "QMT_PROBE_SYMBOL": "600519.SH",
        }
    )

    assert config.account_id == "acct1"
    assert config.userdata_path == r"C:\qmt\userdata_mini"
    assert config.symbol == "600519.SH"
    assert "should-not-appear" not in repr(config)


def test_probe_reports_missing_xtquant_without_raising() -> None:
    result = run_readonly_probe(
        QmtLiveProbeConfig(account_id="acct1", userdata_path=None, symbol="600519.SH"),
        importer=lambda: None,
    )

    assert result.status == "blocked"
    assert result.checks["xtquant_import"] is False
    assert "xtquant" in result.reason


def test_probe_does_not_call_order_stock() -> None:
    calls: list[str] = []

    class FakeTrader:
        def __init__(self, path: str, session: int):
            calls.append(f"init:{path}:{session}")

        def start(self) -> int:
            calls.append("start")
            return 0

        def connect(self) -> int:
            calls.append("connect")
            return 0

        def get_stock_account(self, account_id: str) -> dict:
            calls.append(f"account:{account_id}")
            return {"account_id": account_id}

        def order_stock(self, *args, **kwargs):  # pragma: no cover - must not run
            calls.append("order_stock")
            raise AssertionError("readonly probe must not place orders")

    xtdata = types.SimpleNamespace(
        get_market_data_ex=lambda **kwargs: {"600519.SH": []},
    )
    xttrader = types.SimpleNamespace(XtQuantTrader=FakeTrader)

    result = run_readonly_probe(
        QmtLiveProbeConfig(
            account_id="acct1",
            userdata_path=r"C:\qmt\userdata_mini",
            symbol="600519.SH",
        ),
        importer=lambda: (xtdata, xttrader),
    )

    assert result.status == "pass"
    assert result.checks["xtquant_import"] is True
    assert result.checks["market_data_read"] is True
    assert result.checks["market_data_health"] is False
    assert result.checks["trader_readonly_handshake"] is True
    assert "order_stock" not in calls


def test_probe_uses_query_account_infos_when_get_stock_account_is_absent() -> None:
    calls: list[str] = []

    class FakeTrader:
        def __init__(self, path: str, session: int):
            calls.append(f"init:{path}:{session}")

        def start(self) -> int:
            calls.append("start")
            return 0

        def connect(self) -> int:
            calls.append("connect")
            return 0

        def query_account_infos(self) -> list:
            calls.append("query_account_infos")
            return []

    xtdata = types.SimpleNamespace(get_market_data_ex=lambda **kwargs: [])
    xttrader = types.SimpleNamespace(XtQuantTrader=FakeTrader)

    result = run_readonly_probe(
        QmtLiveProbeConfig(
            account_id="acct1",
            userdata_path=r"C:\qmt\userdata_mini",
            symbol="600519.SH",
        ),
        importer=lambda: (xtdata, xttrader),
    )

    assert result.status == "pass"
    assert result.checks["market_data_health"] is False
    assert result.checks["trader_readonly_handshake"] is True
    assert "query_account_infos" in calls


def test_probe_blocks_trader_handshake_without_userdata_path() -> None:
    xtdata = types.SimpleNamespace(get_market_data_ex=lambda **kwargs: [])
    xttrader = types.SimpleNamespace()

    result = run_readonly_probe(
        QmtLiveProbeConfig(account_id="acct1", userdata_path=None, symbol="600519.SH"),
        importer=lambda: (xtdata, xttrader),
    )

    assert result.status == "blocked"
    assert result.checks["xtquant_import"] is True
    assert result.checks["market_data_read"] is True
    assert result.checks["market_data_health"] is False
    assert result.checks["trader_readonly_handshake"] is False
    assert "QMT_USERDATA_PATH" in result.reason


def test_probe_market_data_health_passes_when_full_tick_available() -> None:
    class FakeTrader:
        def __init__(self, path: str, session: int):
            pass

        def start(self) -> int:
            return 0

        def connect(self) -> int:
            return 0

        def get_stock_account(self, account_id: str) -> dict:
            return {"account_id": account_id}

    xtdata = types.SimpleNamespace(
        get_market_data_ex=lambda **kwargs: {"600519.SH": []},
        get_full_tick=lambda symbols: {"600519.SH": {"lastPrice": 10.0}},
    )
    xttrader = types.SimpleNamespace(XtQuantTrader=FakeTrader)

    result = run_readonly_probe(
        QmtLiveProbeConfig(
            account_id="acct1",
            userdata_path=r"C:\qmt\userdata_mini",
            symbol="600519.SH",
        ),
        importer=lambda: (xtdata, xttrader),
    )

    assert result.status == "pass"
    assert result.checks["market_data_health"] is True


def test_probe_market_data_health_blocks_when_tick_and_recent_bar_empty() -> None:
    class FakeTrader:
        def __init__(self, path: str, session: int):
            pass

        def start(self) -> int:
            return 0

        def connect(self) -> int:
            return 0

        def get_stock_account(self, account_id: str) -> dict:
            return {"account_id": account_id}

    xtdata = types.SimpleNamespace(
        get_market_data_ex=lambda **kwargs: {"600519.SH": []},
        get_full_tick=lambda symbols: {},
    )
    xttrader = types.SimpleNamespace(XtQuantTrader=FakeTrader)

    result = run_readonly_probe(
        QmtLiveProbeConfig(
            account_id="acct1",
            userdata_path=r"C:\qmt\userdata_mini",
            symbol="600519.SH",
        ),
        importer=lambda: (xtdata, xttrader),
    )

    assert result.status == "pass"
    assert result.checks["market_data_health"] is False
