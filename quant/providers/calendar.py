"""A股交易日历：包装 exchange_calendars 的 XSHG 日历，并叠加人工补班 overlay。

XSHG（上交所）与 XSHE（深交所）共享同一份会话日历。exchange_calendars 不识别
A 股的"周末补班交易日"（如 2024-02-04 周日因春节调休而开市），故用 MAKEUP_TRADING_DAYS
常量做人工 overlay：补班日（本该休但上班）补回为交易日；调休假（本该交易但放假）
通常已落在 xcals 的假期区间内，无需额外处理。

注意：overlay 为人工维护，需定期同步交易所年度节假日/调休公告。
"""

from datetime import date
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

# A 股已知补班交易日（本该休但上班的日子）。人工维护，按交易所年度公告同步。
# 来源：国务院办公厅发布的年度节假日安排及沪深交易所通知。
MAKEUP_TRADING_DAYS: frozenset[date] = frozenset(
    {
        date(2024, 2, 4),    # 春节补班
        date(2024, 4, 7),    # 清明补班
        date(2024, 4, 28),   # 五一补班
        date(2024, 9, 29),   # 国庆/中秋补班
        date(2024, 10, 12),  # 国庆补班
    }
)


@lru_cache(maxsize=1)
def _get_calendar() -> xcals.ExchangeCalendar:
    # 模块级单例缓存，避免重复加载日历数据。
    return xcals.get_calendar("XSHG")


class TradingCalendar:
    """A股交易日历，叠加补班 overlay。"""

    def is_trading_day(self, d: date) -> bool:
        # 先查 overlay：补班日直接判定为交易日，绕过 xcals 的周末限制。
        if d in MAKEUP_TRADING_DAYS:
            return True
        return bool(_get_calendar().is_session(pd.Timestamp(d)))

    def trading_days(self, start: date, end: date) -> list[date]:
        # 先取 xcals 在区间内的会话日，再补回落在区间内的补班日。
        cal = _get_calendar()
        sessions = [
            ts.date() for ts in cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        ]
        sessions.extend(
            d for d in MAKEUP_TRADING_DAYS if start <= d <= end and d not in sessions
        )
        sessions.sort()
        return sessions
