from dataclasses import dataclass

from quant.events import BarEvent, EventBus


def test_bar_event_is_dataclass():
    # BarEvent 必须是 dataclass，字段 symbol/freq/ts/close/volume
    ev = BarEvent(symbol="600519", freq="1d", ts=__import__("datetime").datetime(2024, 1, 1), close=1800.0, volume=10000)
    assert ev.symbol == "600519"
    assert ev.freq == "1d"
    assert ev.close == 1800.0
    assert ev.volume == 10000


def test_subscribe_and_publish_single():
    # subscribe 注册后 publish 派发给该类型所有订阅者
    bus = EventBus()
    received: list[BarEvent] = []
    bus.subscribe(BarEvent, received.append)
    ev = BarEvent(symbol="000001", freq="1d", ts=__import__("datetime").datetime(2024, 1, 2), close=10.0, volume=5)
    bus.publish(ev)
    assert received == [ev]


def test_multiple_subscribers_all_receive():
    # 多订阅者都收到同一事件
    bus = EventBus()
    a: list[BarEvent] = []
    b: list[BarEvent] = []
    bus.subscribe(BarEvent, a.append)
    bus.subscribe(BarEvent, b.append)
    ev = BarEvent(symbol="000002", freq="1d", ts=__import__("datetime").datetime(2024, 1, 3), close=20.0, volume=8)
    bus.publish(ev)
    assert a == [ev]
    assert b == [ev]


def test_publish_no_subscribers_does_not_raise():
    # 发布一个没有订阅者的事件类型不报错
    bus = EventBus()
    ev = BarEvent(symbol="000003", freq="1d", ts=__import__("datetime").datetime(2024, 1, 4), close=30.0, volume=1)
    # 不应抛异常
    bus.publish(ev)


def test_subscriber_exception_does_not_affect_others():
    # 订阅者抛异常不影响其他订阅者（隔离）
    bus = EventBus()
    received: list[BarEvent] = []

    def boom(_: BarEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(BarEvent, boom)
    bus.subscribe(BarEvent, received.append)
    ev = BarEvent(symbol="000004", freq="1d", ts=__import__("datetime").datetime(2024, 1, 5), close=40.0, volume=2)
    # 不应抛异常
    bus.publish(ev)
    assert received == [ev]
