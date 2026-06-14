"""主体行为学习 Task 1 测试：Actor 抽象 + 样本库（设计 v0.5 §4.9.1 / §4.9.2）。

覆盖点：
- ActorKind 4 种枚举（self / hot_money / northbound / institution）
- ActorTrade 字段：symbol / time / side / price / volume / realized_pnl / context
- Actor.add_trade + trades_in 时间范围过滤（闭区间，超范围剔除）
- SampleLibrary.by_kind 按 kind 过滤
- bias_declarations：仅列出非空 bias_note 的主体（HOT_MONEY 默认带"仅上榜股样本"声明）
- small_sample_actors：trades 数 < min_trades 的主体（自身小样本降级标注候选）
- all_trades(kind) 仅返回该 kind 的 trades

数据来源均带偏差声明（游资仅上榜股、北向沪深股通、自身 QMT 小样本）。

TDD：本文件先于 quant/actor/ 实现，import 失败为预期红线。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from quant.actor.model import Actor, ActorKind, ActorTrade
from quant.actor.sample_lib import SampleLibrary


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_trades() -> list[ActorTrade]:
    """2024-01 内 3 笔 buy/sell。"""
    return [
        ActorTrade(
            symbol="600519",
            time=datetime(2024, 1, 5, 10, 0),
            side="buy",
            price=1800.0,
            volume=100,
        ),
        ActorTrade(
            symbol="600519",
            time=datetime(2024, 1, 10, 14, 30),
            side="sell",
            price=1820.0,
            volume=100,
            realized_pnl=2000.0,
        ),
        ActorTrade(
            symbol="000001",
            time=datetime(2024, 1, 15, 9, 35),
            side="buy",
            price=12.0,
            volume=500,
        ),
    ]


@pytest.fixture
def hot_money_actor(base_trades: list[ActorTrade]) -> Actor:
    """游资主体：龙虎榜席位（仅上榜股样本）。"""
    return Actor(
        id="seat_zhangjiagang",
        kind=ActorKind.HOT_MONEY,
        trades=list(base_trades),
    )


@pytest.fixture
def self_actor() -> Actor:
    """自身主体：QMT 导出，小样本。"""
    return Actor(
        id="self_qmt",
        kind=ActorKind.SELF,
        trades=[
            ActorTrade(
                symbol="600519",
                time=datetime(2024, 1, 3, 9, 30),
                side="buy",
                price=1790.0,
                volume=200,
            )
        ],
    )


# ---------------------------------------------------------------------------
# ActorKind / ActorTrade
# ---------------------------------------------------------------------------


def test_actor_kind_enum() -> None:
    """4 种 kind：self / hot_money / northbound / institution。"""
    kinds = {k.value for k in ActorKind}
    assert kinds == {"self", "hot_money", "northbound", "institution"}


def test_actor_trade_fields() -> None:
    """ActorTrade 字段完整，默认值正确（realized_pnl=0, context={}）。"""
    t = ActorTrade(
        symbol="600519",
        time=datetime(2024, 1, 5, 10, 0),
        side="buy",
        price=1800.0,
        volume=100,
    )
    assert t.symbol == "600519"
    assert t.side == "buy"
    assert t.price == 1800.0
    assert t.volume == 100
    assert t.realized_pnl == 0.0
    assert t.context == {}


# ---------------------------------------------------------------------------
# Actor
# ---------------------------------------------------------------------------


def test_actor_add_and_query(base_trades: list[ActorTrade]) -> None:
    """add_trade 入队，trades_in 闭区间时间过滤，超范围剔除。"""
    actor = Actor(id="a1", kind=ActorKind.SELF)
    for t in base_trades:
        actor.add_trade(t)
    assert len(actor.trades) == 3
    # 闭区间 [2024-01-05, 2024-01-10]
    in_range = actor.trades_in(
        datetime(2024, 1, 5, 0, 0), datetime(2024, 1, 10, 23, 59)
    )
    assert len(in_range) == 2
    # 超范围：只取 2024-01-15 一笔
    late = actor.trades_in(
        datetime(2024, 1, 12), datetime(2024, 1, 20)
    )
    assert len(late) == 1
    assert late[0].symbol == "000001"


# ---------------------------------------------------------------------------
# SampleLibrary
# ---------------------------------------------------------------------------


def test_sample_library_by_kind(
    hot_money_actor: Actor, self_actor: Actor
) -> None:
    """2 HOT_MONEY + 1 SELF → by_kind(HOT_MONEY)=2。"""
    lib = SampleLibrary()
    lib.add(hot_money_actor)
    lib.add(
        Actor(id="seat_other", kind=ActorKind.HOT_MONEY, trades=[])
    )
    lib.add(self_actor)
    hm = lib.by_kind(ActorKind.HOT_MONEY)
    assert len(hm) == 2
    assert all(a.kind == ActorKind.HOT_MONEY for a in hm)


def test_bias_declarations(hot_money_actor: Actor, self_actor: Actor) -> None:
    """HOT_MONEY 默认 bias_note 含"仅上榜股样本"声明；bias_declarations 仅含非空。"""
    lib = SampleLibrary()
    lib.add(hot_money_actor)
    lib.add(self_actor)  # bias_note 默认空
    decls = lib.bias_declarations()
    # HOT_MONEY 默认声明必须出现
    assert hot_money_actor.id in decls
    assert "仅上榜股样本" in decls[hot_money_actor.id]
    # SELF 默认无声明 → 不出现
    assert self_actor.id not in decls


def test_small_sample_detection() -> None:
    """trades < min_trades（默认 30）的 actor 被列为小样本。"""
    small = Actor(id="self_qmt", kind=ActorKind.SELF)
    for i in range(5):
        small.add_trade(
            ActorTrade(
                symbol="600519",
                time=datetime(2024, 1, i + 1, 10, 0),
                side="buy",
                price=1800.0,
                volume=100,
            )
        )
    large = Actor(id="big_seat", kind=ActorKind.HOT_MONEY)
    for i in range(50):
        large.add_trade(
            ActorTrade(
                symbol="000001",
                time=datetime(2024, 1, (i % 28) + 1, 10, 0),
                side="sell",
                price=12.0,
                volume=100,
            )
        )
    lib = SampleLibrary()
    lib.add(small)
    lib.add(large)
    flagged = lib.small_sample_actors(min_trades=30)
    assert small.id in flagged
    assert large.id not in flagged


def test_all_trades_filter(
    hot_money_actor: Actor, self_actor: Actor
) -> None:
    """all_trades(kind) 仅返回该 kind；all_trades(None) 返回全部。"""
    lib = SampleLibrary()
    lib.add(hot_money_actor)
    lib.add(self_actor)
    # HOT_MONEY：3 笔（base_trades）
    hm_trades = lib.all_trades(ActorKind.HOT_MONEY)
    assert len(hm_trades) == 3
    # SELF：1 笔
    self_trades = lib.all_trades(ActorKind.SELF)
    assert len(self_trades) == 1
    # None：全部 4 笔
    all_t = lib.all_trades()
    assert len(all_t) == 4
