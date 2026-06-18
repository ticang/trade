import pytest
import sys
import types
from datetime import date
from probes.data_sources import fetch_akshare_daily, fetch_baostock_daily, derive_available_at
import pandas as pd


@pytest.mark.network
def test_akshare_daily_has_required_fields():
    df = fetch_akshare_daily(symbol="000001", start=date(2024, 3, 1), end=date(2024, 3, 7))
    required = {"open", "high", "low", "close", "volume", "trade_date"}
    assert required.issubset(set(df.columns)), f"missing: {required - set(df.columns)}"
    assert len(df) > 0


def test_akshare_daily_retries_transient_disconnect(monkeypatch):
    calls = {"count": 0}

    def stock_zh_a_hist(**kwargs):
        calls["count"] += 1
        calls["last_timeout"] = kwargs.get("timeout")
        if calls["count"] == 1:
            raise ConnectionError("transient disconnect")
        return pd.DataFrame(
            [
                {
                    "日期": "2024-03-01",
                    "开盘": 10.0,
                    "最高": 11.0,
                    "最低": 9.5,
                    "收盘": 10.5,
                    "成交量": 12345,
                }
            ]
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist),
    )

    df = fetch_akshare_daily(
        symbol="000001",
        start=date(2024, 3, 1),
        end=date(2024, 3, 7),
        retries=2,
        timeout=1.5,
    )

    assert calls["count"] == 2
    assert list(df.columns) == ["trade_date", "open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == 10.5
    assert calls["last_timeout"] == 1.5


@pytest.mark.network
def test_baostock_daily_has_required_fields():
    df = fetch_baostock_daily(symbol="sz.000001", start=date(2024, 3, 1), end=date(2024, 3, 7))
    required = {"open", "high", "low", "close", "volume", "trade_date"}
    assert required.issubset(set(df.columns))


def test_available_at_derivable_from_trade_date():
    avail = derive_available_at(trade_date=date(2024, 3, 15))
    # available_at = trade_date + 15:00 (close)
    assert avail.date() == date(2024, 3, 15)
    assert avail.hour == 15
