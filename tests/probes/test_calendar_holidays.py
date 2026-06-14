import pytest
from datetime import date
from probes.calendar_holidays import is_trading_day, trading_days_between

def test_weekday_non_holiday_is_trading_day():
    assert is_trading_day(date(2024, 3, 15)) is True  # Friday

def test_normal_weekend_is_not_trading_day():
    assert is_trading_day(date(2024, 3, 16)) is False  # Saturday

def test_national_holiday_is_not_trading_day():
    assert is_trading_day(date(2024, 10, 1)) is False  # National Day

@pytest.mark.xfail(reason="M-1a known gap: exchange_calendars misses makeup trading days; production overlay in quant/providers/calendar.py fixes this. Probe retained as historical record of the finding.")
def test_makeup_trading_day_is_trading_day():
    # 2024-02-04 (Sunday) was a makeup trading day for Spring Festival.
    assert is_trading_day(date(2024, 2, 4)) is True

def test_trading_days_between_excludes_holidays():
    days = trading_days_between(date(2024, 9, 30), date(2024, 10, 8))
    # Oct 1-7 holiday; Sep 30 and Oct 8 are trading days.
    assert date(2024, 10, 1) not in days
    assert date(2024, 10, 8) in days
