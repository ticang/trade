from datetime import date

from quant.providers.calendar import TradingCalendar


def test_normal_weekday_trading():
    assert TradingCalendar().is_trading_day(date(2024, 3, 15)) is True  # 周五


def test_weekend_not_trading():
    assert TradingCalendar().is_trading_day(date(2024, 3, 16)) is False


def test_holiday_not_trading():
    assert TradingCalendar().is_trading_day(date(2024, 10, 1)) is False  # 国庆


def test_makeup_trading_day_via_overlay():
    assert TradingCalendar().is_trading_day(date(2024, 2, 4)) is True  # 周日补班，overlay 命中


def test_range_excludes_holidays():
    days = TradingCalendar().trading_days(date(2024, 9, 30), date(2024, 10, 8))
    assert date(2024, 10, 1) not in days
    assert date(2024, 10, 8) in days
