from datetime import datetime, timedelta
from time import sleep

from quant.clock import BacktestClock, LiveClock


def test_live_clock_now_returns_real_datetime():
    # LiveClock 应返回真实的当前时刻
    clock = LiveClock()
    before = datetime.now()
    result = clock.now()
    after = datetime.now()
    assert isinstance(result, datetime)
    assert before <= result <= after


def test_backtest_clock_initial_value():
    # BacktestClock 初值可设，now() 返回该值
    start = datetime(2024, 1, 1, 9, 30)
    clock = BacktestClock(start)
    assert clock.now() == start


def test_backtest_clock_advance_timedelta():
    # advance(timedelta) 按偏移前进
    start = datetime(2024, 1, 1, 9, 30)
    clock = BacktestClock(start)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == start + timedelta(minutes=5)


def test_backtest_clock_advance_datetime():
    # advance(datetime) 直接跳到该时刻
    start = datetime(2024, 1, 1, 9, 30)
    target = datetime(2024, 1, 2, 14, 0)
    clock = BacktestClock(start)
    clock.advance(target)
    assert clock.now() == target


def test_backtest_clock_now_is_deterministic():
    # 回测时钟不随真实时间变化：连续两次 now() 间隔 sleep 后仍相等
    start = datetime(2024, 1, 1, 9, 30)
    clock = BacktestClock(start)
    first = clock.now()
    sleep(0.01)
    second = clock.now()
    assert first == second
