"""Trading calendar wrapper over exchange_calendars (XSHG/XSHE) with makeup-day handling."""
from datetime import date
import exchange_calendars as xcals
from pandas import Timestamp

_CAL = xcals.get_calendar("XSHG")  # Shanghai; XSHG and XSHE share the same session calendar

def is_trading_day(d: date) -> bool:
    return _CAL.is_session(Timestamp(d))

def trading_days_between(start: date, end: date) -> list[date]:
    sessions = _CAL.sessions_in_range(Timestamp(start), Timestamp(end))
    return [ts.date() for ts in sessions]
