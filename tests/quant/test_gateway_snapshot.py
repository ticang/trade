from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from quant.gateway.snapshot import SnapshotMarketDataGateway


def test_snapshot_health_degraded_for_intraday_rows():
    df = pd.DataFrame({
        "symbol": ["600519.SH"],
        "freq": ["1m"],
        "ts": [datetime(2024, 3, 15, 15)],
        "close": [10.0],
        "volume": [100],
        "available_at": [datetime(2024, 3, 15, 15, 1)],
    })
    gw = SnapshotMarketDataGateway(df, source="backup")

    health = gw.health(["600519.SH"], "1m")

    assert health.status == "DEGRADED"
    assert health.quality == "DELAYED"
    assert health.source == "backup"


def test_snapshot_history_filters_symbol_freq_time_and_as_of():
    df = pd.DataFrame({
        "symbol": ["600519.SH", "600519.SH", "000001.SZ"],
        "freq": ["1m", "1m", "1m"],
        "ts": [
            datetime(2024, 3, 15, 14, 59),
            datetime(2024, 3, 15, 15, 0),
            datetime(2024, 3, 15, 15, 0),
        ],
        "close": [9.9, 10.0, 8.0],
        "volume": [90, 100, 80],
        "available_at": [
            datetime(2024, 3, 15, 14, 59),
            datetime(2024, 3, 15, 15, 1),
            datetime(2024, 3, 15, 15, 0),
        ],
    })
    gw = SnapshotMarketDataGateway(df, source="backup")

    got = gw.history(
        "600519.SH",
        "1m",
        datetime(2024, 3, 15, 14, 58),
        datetime(2024, 3, 15, 15, 0),
        as_of=datetime(2024, 3, 15, 15, 0),
    )

    assert len(got) == 1
    assert got.iloc[0]["close"] == 9.9


def test_snapshot_bar_at_respects_available_at():
    df = pd.DataFrame({
        "symbol": ["600519.SH"],
        "freq": ["1m"],
        "ts": [datetime(2024, 3, 15, 15)],
        "close": [10.0],
        "volume": [100],
        "available_at": [datetime(2024, 3, 15, 15, 1)],
    })
    gw = SnapshotMarketDataGateway(df, source="backup")

    hidden = gw.bar_at(
        "600519.SH",
        "1m",
        datetime(2024, 3, 15, 15),
        datetime(2024, 3, 15, 15),
    )
    visible = gw.bar_at(
        "600519.SH",
        "1m",
        datetime(2024, 3, 15, 15),
        datetime(2024, 3, 15, 15, 1),
    )

    assert hidden is None
    assert visible["close"] == 10.0


def test_snapshot_subscribe_emits_latest_visible_bar_once():
    df = pd.DataFrame({
        "symbol": ["600519.SH", "600519.SH"],
        "freq": ["1m", "1m"],
        "ts": [datetime(2024, 3, 15, 14, 59), datetime(2024, 3, 15, 15)],
        "close": [9.9, 10.0],
        "volume": [90, 100],
        "available_at": [datetime(2024, 3, 15, 14, 59), datetime(2024, 3, 15, 15)],
    })
    gw = SnapshotMarketDataGateway(df, source="backup")
    on_bar = MagicMock()

    gw.subscribe(["600519.SH"], "1m", on_bar)

    on_bar.assert_called_once()
    event = on_bar.call_args[0][0]
    assert event.symbol == "600519.SH"
    assert event.freq == "1m"
    assert event.close == 10.0
