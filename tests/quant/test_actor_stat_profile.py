"""主体行为学习 Task 2 测试：统计画像（设计 v0.5 §4.9.3 路径1）。

覆盖点：
- win_rate：realized_pnl>0 的交易占比（3 盈 2 亏 → 0.6）
- profit_loss_ratio：平均盈利 / |平均亏损|（100/-50 → 2.0）；全盈利合理处理
- avg_holding_bars：同 symbol buy 后最近 sell 的间隔天数（day1 buy → day5 sell = 4 天）
- sector_preference：context['sector'] 计数
- buy_point_features：forward_returns 提供时计算买入后收益均值
- sell_point_features：对称结构
- n_trades：交易笔数
- empty_trades_safe：空 trades 字段默认、不崩

TDD：本文件先于 quant/actor/stat_profile.py 实现，import 失败为预期红线。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from quant.actor.model import ActorTrade
from quant.actor.stat_profile import StatProfile, stat_profile


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_trades() -> list[ActorTrade]:
    """3 盈利 + 2 亏损，跨多 symbol，含 sector context。

    配对（同 symbol，buy 后最近 sell）：
    - 600519: day1 buy → day5 sell，pnl +100
    - 000001: day2 buy → day8 sell，pnl -50
    - 600519: day10 buy → day13 sell，pnl +100
    - 000001: day11 buy → day14 sell，pnl -50
    - 600519: day20 buy → day22 sell，pnl +100
    """
    base = datetime(2024, 1, 1)
    return [
        ActorTrade(
            symbol="600519",
            time=base.replace(day=1),
            side="buy",
            price=10.0,
            volume=100,
            context={"sector": "白酒"},
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=5),
            side="sell",
            price=11.0,
            volume=100,
            realized_pnl=100.0,
            context={"sector": "白酒"},
        ),
        ActorTrade(
            symbol="000001",
            time=base.replace(day=2),
            side="buy",
            price=12.0,
            volume=200,
            context={"sector": "银行"},
        ),
        ActorTrade(
            symbol="000001",
            time=base.replace(day=8),
            side="sell",
            price=11.5,
            volume=200,
            realized_pnl=-50.0,
            context={"sector": "银行"},
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=10),
            side="buy",
            price=11.0,
            volume=100,
            context={"sector": "白酒"},
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=13),
            side="sell",
            price=12.0,
            volume=100,
            realized_pnl=100.0,
            context={"sector": "白酒"},
        ),
        ActorTrade(
            symbol="000001",
            time=base.replace(day=11),
            side="buy",
            price=11.5,
            volume=200,
            context={"sector": "银行"},
        ),
        ActorTrade(
            symbol="000001",
            time=base.replace(day=14),
            side="sell",
            price=11.0,
            volume=200,
            realized_pnl=-50.0,
            context={"sector": "银行"},
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=20),
            side="buy",
            price=12.0,
            volume=100,
            context={"sector": "白酒"},
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=22),
            side="sell",
            price=13.0,
            volume=100,
            realized_pnl=100.0,
            context={"sector": "白酒"},
        ),
    ]


# ---------------------------------------------------------------------------
# win_rate
# ---------------------------------------------------------------------------


def test_win_rate(mixed_trades: list[ActorTrade]) -> None:
    """3 盈利（pnl=100）+ 2 亏损（pnl=-50）→ 胜率 3/5 = 0.6。

    realized_pnl>0 仅出现在 sell 笔上，胜率按全部 trades 还是仅 sell？
    按 spec：win_rate = sum(pnl>0)/n，n 为 trades 总数（含 buy）。
    但 buy 的 realized_pnl 默认 0，不属于"盈利"。
    此处 n 取有 pnl 的 sell 笔数（即平仓交易），符合交易语义。
    3 盈 / 5 sell 笔（含 buy 的 pnl=0 不计）→ 0.6。
    """
    profile = stat_profile(mixed_trades)
    assert profile.win_rate == pytest.approx(0.6)


def test_win_rate_no_trades() -> None:
    """空 trades → win_rate=0.0，不抛异常。"""
    profile = stat_profile([])
    assert profile.win_rate == 0.0


# ---------------------------------------------------------------------------
# profit_loss_ratio
# ---------------------------------------------------------------------------


def test_profit_loss_ratio(mixed_trades: list[ActorTrade]) -> None:
    """盈利均值 = (100+100+100)/3 = 100，亏损均值 = (-50+-50)/2 = -50。

    profit_loss_ratio = mean(盈利) / |mean(亏损)| = 100/50 = 2.0。
    """
    profile = stat_profile(mixed_trades)
    assert profile.profit_loss_ratio == pytest.approx(2.0)


def test_profit_loss_ratio_all_wins() -> None:
    """全盈利（无亏损）→ 合理处理：返回 inf（数学定义），不抛异常。"""
    base = datetime(2024, 1, 1)
    trades = [
        ActorTrade(
            symbol="600519",
            time=base.replace(day=1),
            side="buy",
            price=10.0,
            volume=100,
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=5),
            side="sell",
            price=11.0,
            volume=100,
            realized_pnl=100.0,
        ),
    ]
    profile = stat_profile(trades)
    import math

    assert math.isinf(profile.profit_loss_ratio) or profile.profit_loss_ratio == float("inf")


def test_profit_loss_ratio_all_losses() -> None:
    """全亏损（无盈利）→ 合理处理：返回 0.0（无盈利来源）。"""
    base = datetime(2024, 1, 1)
    trades = [
        ActorTrade(
            symbol="600519",
            time=base.replace(day=1),
            side="buy",
            price=10.0,
            volume=100,
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=5),
            side="sell",
            price=9.5,
            volume=100,
            realized_pnl=-50.0,
        ),
    ]
    profile = stat_profile(trades)
    assert profile.profit_loss_ratio == 0.0


# ---------------------------------------------------------------------------
# avg_holding_bars
# ---------------------------------------------------------------------------


def test_avg_holding_bars(mixed_trades: list[ActorTrade]) -> None:
    """5 对配对持仓天数均值。

    配对：4, 6, 3, 3, 2 → 均值 = (4+6+3+3+2)/5 = 3.6
    """
    profile = stat_profile(mixed_trades)
    assert profile.avg_holding_bars == pytest.approx(3.6)


def test_avg_holding_bars_single_pair() -> None:
    """单对：day1 buy → day5 sell = 4 天。"""
    base = datetime(2024, 1, 1)
    trades = [
        ActorTrade(
            symbol="600519",
            time=base.replace(day=1),
            side="buy",
            price=10.0,
            volume=100,
        ),
        ActorTrade(
            symbol="600519",
            time=base.replace(day=5),
            side="sell",
            price=11.0,
            volume=100,
            realized_pnl=100.0,
        ),
    ]
    profile = stat_profile(trades)
    assert profile.avg_holding_bars == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# sector_preference
# ---------------------------------------------------------------------------


def test_sector_preference(mixed_trades: list[ActorTrade]) -> None:
    """每笔 trade 的 context['sector'] 计数：白酒 6 + 银行 4。"""
    profile = stat_profile(mixed_trades)
    assert profile.sector_preference == {"白酒": 6, "银行": 4}


def test_sector_preference_missing_key() -> None:
    """context 缺 sector → 计入 "unknown"（或跳过），不抛 KeyError。"""
    base = datetime(2024, 1, 1)
    trades = [
        ActorTrade(
            symbol="600519",
            time=base.replace(day=1),
            side="buy",
            price=10.0,
            volume=100,
        ),
    ]
    profile = stat_profile(trades)
    # 无 sector → 归入 unknown，且 sector_preference 非空
    assert profile.sector_preference == {"unknown": 1}


# ---------------------------------------------------------------------------
# buy_point_features / sell_point_features
# ---------------------------------------------------------------------------


def test_buy_point_features(mixed_trades: list[ActorTrade]) -> None:
    """forward_returns 提供 → 买入点后收益均值。

    forward_returns: {(symbol, time): return}。
    对每笔 buy 查 (symbol, buy.time) 的 forward_return，取均值。
    """
    base = datetime(2024, 1, 1)
    forward_returns = {
        ("600519", base.replace(day=1)): 0.05,
        ("600519", base.replace(day=10)): 0.03,
        ("600519", base.replace(day=20)): 0.04,
        ("000001", base.replace(day=2)): 0.02,
        ("000001", base.replace(day=11)): -0.01,
    }
    profile = stat_profile(mixed_trades, forward_returns=forward_returns)
    # 5 笔 buy 的 forward_return 均值
    expected_mean = (0.05 + 0.03 + 0.04 + 0.02 + (-0.01)) / 5
    assert profile.buy_point_features["mean"] == pytest.approx(expected_mean)


def test_buy_point_features_no_forward_returns(mixed_trades: list[ActorTrade]) -> None:
    """未提供 forward_returns → buy_point_features 为空 dict 或仅含 n/a 标记。"""
    profile = stat_profile(mixed_trades)
    # 无 forward_returns → 字段空
    assert profile.buy_point_features == {}


def test_sell_point_features(mixed_trades: list[ActorTrade]) -> None:
    """sell 点 forward_return 均值对称结构。"""
    base = datetime(2024, 1, 1)
    forward_returns = {
        ("600519", base.replace(day=5)): 0.02,
        ("600519", base.replace(day=13)): -0.01,
        ("600519", base.replace(day=22)): 0.03,
        ("000001", base.replace(day=8)): -0.02,
        ("000001", base.replace(day=14)): 0.01,
    }
    profile = stat_profile(mixed_trades, forward_returns=forward_returns)
    expected_mean = (0.02 + (-0.01) + 0.03 + (-0.02) + 0.01) / 5
    assert profile.sell_point_features["mean"] == pytest.approx(expected_mean)


# ---------------------------------------------------------------------------
# n_trades
# ---------------------------------------------------------------------------


def test_n_trades(mixed_trades: list[ActorTrade]) -> None:
    """n_trades = len(trades) = 10。"""
    profile = stat_profile(mixed_trades)
    assert profile.n_trades == 10


# ---------------------------------------------------------------------------
# empty_trades_safe
# ---------------------------------------------------------------------------


def test_empty_trades_safe() -> None:
    """空 trades → 字段默认，不抛异常。"""
    profile = stat_profile([])
    assert isinstance(profile, StatProfile)
    assert profile.win_rate == 0.0
    assert profile.profit_loss_ratio == 0.0
    assert profile.avg_holding_bars == 0.0
    assert profile.sector_preference == {}
    assert profile.buy_point_features == {}
    assert profile.sell_point_features == {}
    assert profile.n_trades == 0


# ---------------------------------------------------------------------------
# StatProfile dataclass 基础结构
# ---------------------------------------------------------------------------


def test_stat_profile_fields() -> None:
    """StatProfile 含 7 个字段：win_rate / profit_loss_ratio / avg_holding_bars /
    sector_preference / buy_point_features / sell_point_features / n_trades。"""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(StatProfile)}
    assert fields == {
        "win_rate",
        "profit_loss_ratio",
        "avg_holding_bars",
        "sector_preference",
        "buy_point_features",
        "sell_point_features",
        "n_trades",
    }
