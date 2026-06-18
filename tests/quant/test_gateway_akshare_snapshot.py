import sys
import types
from datetime import date, datetime

import pandas as pd

from quant.gateway.akshare_snapshot import AkShareDailySnapshotGateway


def test_akshare_daily_snapshot_fetches_standard_snapshot_rows(monkeypatch):
    calls = []

    def stock_zh_a_hist(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([
            {
                "日期": "2024-03-15",
                "开盘": 9.8,
                "最高": 10.2,
                "最低": 9.7,
                "收盘": 10.0,
                "成交量": 100,
            }
        ])

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist),
    )

    gw = AkShareDailySnapshotGateway.fetch(
        ["600519.SH"],
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
    )
    df = gw.history(
        "600519.SH",
        "1d",
        datetime(2024, 3, 15),
        datetime(2024, 3, 15, 23),
    )

    assert calls[0]["symbol"] == "600519"
    assert calls[0]["period"] == "daily"
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "600519.SH"
    assert df.iloc[0]["freq"] == "1d"
    assert df.iloc[0]["close"] == 10.0
    assert df.iloc[0]["available_at"] == pd.Timestamp(datetime(2024, 3, 15, 15))


def test_akshare_daily_snapshot_retries_transient_error(monkeypatch):
    calls = {"count": 0}

    def stock_zh_a_hist(**kwargs):
        calls["count"] += 1
        calls["last_timeout"] = kwargs.get("timeout")
        if calls["count"] == 1:
            raise ConnectionError("transient")
        return pd.DataFrame([
            {
                "日期": "2024-03-15",
                "开盘": 9.8,
                "最高": 10.2,
                "最低": 9.7,
                "收盘": 10.0,
                "成交量": 100,
            }
        ])

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist),
    )

    gw = AkShareDailySnapshotGateway.fetch(
        ["600519.SH"],
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
        retries=2,
        timeout=1.5,
    )

    assert calls["count"] == 2
    assert calls["last_timeout"] == 1.5
    assert gw.health(["600519.SH"], "1d").status == "PASS"


def test_akshare_daily_snapshot_accepts_plain_six_digit_symbol(monkeypatch):
    def stock_zh_a_hist(**kwargs):
        assert kwargs["symbol"] == "000001"
        return pd.DataFrame([
            {
                "日期": "2024-03-15",
                "开盘": 9.8,
                "最高": 10.2,
                "最低": 9.7,
                "收盘": 10.0,
                "成交量": 100,
            }
        ])

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist),
    )

    gw = AkShareDailySnapshotGateway.fetch(
        ["000001"],
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
    )

    assert gw.health(["000001"], "1d").status == "PASS"
