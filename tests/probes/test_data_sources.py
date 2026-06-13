import pytest
from datetime import date
from probes.data_sources import fetch_akshare_daily, fetch_baostock_daily, derive_available_at


@pytest.mark.network
def test_akshare_daily_has_required_fields():
    df = fetch_akshare_daily(symbol="000001", start=date(2024, 3, 1), end=date(2024, 3, 7))
    required = {"open", "high", "low", "close", "volume", "trade_date"}
    assert required.issubset(set(df.columns)), f"missing: {required - set(df.columns)}"
    assert len(df) > 0


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
