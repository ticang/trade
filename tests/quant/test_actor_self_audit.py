"""主体行为学习 Task 6 测试：自身画像降级 — 审计 + 规则提醒（设计 v0.5 §4.9.5）。

自身 QMT 数据小样本，统计建模无意义，降级为"行为审计 + 规则化提醒"。
提醒种类：
- chasing_high：买入价接近当日高点（涨幅小于阈值内追入）
- cutting_loss：卖出实现亏损低于阈值（割肉）
- holding_too_long：同 symbol buy→sell 间隔过长
- frequent_trading：某日成交数过多（频繁交易）
- small_sample：trades 数 < 阈值 → 降级标注（非建模对象）

TDD：本文件先于 quant/actor/self_audit.py 实现，import 失败为预期红线。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant.actor.model import ActorTrade
from quant.actor.self_audit import Reminder, SelfAudit, SelfAuditResult


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _buy(symbol: str, t: datetime, price: float, volume: float = 100) -> ActorTrade:
    return ActorTrade(symbol=symbol, time=t, side="buy", price=price, volume=volume)


def _sell(
    symbol: str,
    t: datetime,
    price: float,
    realized_pnl: float,
    volume: float = 100,
) -> ActorTrade:
    return ActorTrade(
        symbol=symbol,
        time=t,
        side="sell",
        price=price,
        volume=volume,
        realized_pnl=realized_pnl,
    )


# ---------------------------------------------------------------------------
# 1. chasing_high
# ---------------------------------------------------------------------------


def test_chasing_high_detected() -> None:
    """买入价接近当日高点 → chasing_high 提醒。

    构造：当日高点 10.00，买入价 9.80（距高点 2% < 5% 阈值）→ 追高。
    """
    buy = _buy("600519", datetime(2024, 1, 5, 14, 30), 9.80)
    day_highs = {("600519", datetime(2024, 1, 5).date()): 10.00}
    res = SelfAudit(chase_threshold=0.05).audit([buy], day_highs=day_highs)
    kinds = [r.kind for r in res.reminders]
    assert "chasing_high" in kinds
    r = next(r for r in res.reminders if r.kind == "chasing_high")
    assert r.symbol == "600519"
    assert r.severity in {"info", "warn"}


def test_chasing_high_below_threshold_no_reminder() -> None:
    """买入价距高点 > 阈值 → 不算追高。当日高点 10.00，买 8.00（距 20%）。"""
    buy = _buy("600519", datetime(2024, 1, 5, 10, 0), 8.00)
    day_highs = {("600519", datetime(2024, 1, 5).date()): 10.00}
    res = SelfAudit(chase_threshold=0.05).audit([buy], day_highs=day_highs)
    assert not any(r.kind == "chasing_high" for r in res.reminders)


def test_chasing_high_no_day_high_skipped() -> None:
    """buy 无对应 day_high 记录 → 跳过（无法判定）。"""
    buy = _buy("600519", datetime(2024, 1, 5, 14, 30), 9.80)
    res = SelfAudit(chase_threshold=0.05).audit([buy], day_highs=None)
    assert not any(r.kind == "chasing_high" for r in res.reminders)


# ---------------------------------------------------------------------------
# 2. cutting_loss
# ---------------------------------------------------------------------------


def test_cutting_loss_detected() -> None:
    """卖出亏损 < -8% → cutting_loss 提醒。

    构造：成本 10.00，卖出 9.00 → realized_pnl_pct = -10% < -8%。
    """
    sell = _sell("600519", datetime(2024, 1, 10, 14, 30), 9.00, realized_pnl=-100.0)
    buy = _buy("600519", datetime(2024, 1, 5, 10, 0), 10.00)
    res = SelfAudit(loss_cut_threshold=-0.08).audit([buy, sell])
    kinds = [r.kind for r in res.reminders]
    assert "cutting_loss" in kinds
    r = next(r for r in res.reminders if r.kind == "cutting_loss")
    assert r.symbol == "600519"


def test_cutting_loss_above_threshold_no_reminder() -> None:
    """卖出盈利或微亏 → 不算割肉。"""
    buy = _buy("600519", datetime(2024, 1, 5, 10, 0), 10.00)
    sell = _sell("600519", datetime(2024, 1, 10, 14, 30), 11.00, realized_pnl=100.0)
    res = SelfAudit(loss_cut_threshold=-0.08).audit([buy, sell])
    assert not any(r.kind == "cutting_loss" for r in res.reminders)


# ---------------------------------------------------------------------------
# 3. holding_too_long
# ---------------------------------------------------------------------------


def test_holding_too_long() -> None:
    """同 symbol buy→sell 间隔 > 60 天 → holding_too_long 提醒。"""
    buy = _buy("600519", datetime(2024, 1, 5, 10, 0), 10.00)
    sell = _sell(
        "600519", datetime(2024, 4, 20, 14, 30), 10.50, realized_pnl=50.0
    )  # 约 106 天
    res = SelfAudit(holding_days_too_long=60).audit([buy, sell])
    kinds = [r.kind for r in res.reminders]
    assert "holding_too_long" in kinds
    r = next(r for r in res.reminders if r.kind == "holding_too_long")
    assert r.symbol == "600519"


def test_holding_within_limit_no_reminder() -> None:
    """持仓 < 60 天 → 不报警。"""
    buy = _buy("600519", datetime(2024, 1, 5, 10, 0), 10.00)
    sell = _sell(
        "600519", datetime(2024, 1, 20, 14, 30), 10.50, realized_pnl=50.0
    )  # 15 天
    res = SelfAudit(holding_days_too_long=60).audit([buy, sell])
    assert not any(r.kind == "holding_too_long" for r in res.reminders)


# ---------------------------------------------------------------------------
# 4. frequent_trading
# ---------------------------------------------------------------------------


def test_frequent_trading() -> None:
    """某日成交 > 5 笔 → frequent_trading 提醒。

    构造：2024-01-05 共 6 笔（>5）→ 触发。
    """
    day = datetime(2024, 1, 5)
    trades = [
        _buy(f"00000{i}", day.replace(hour=9 + i, minute=30), 10.0 + i)
        for i in range(6)
    ]
    res = SelfAudit(frequent_trades_per_day=5).audit(trades)
    kinds = [r.kind for r in res.reminders]
    assert "frequent_trading" in kinds


def test_frequent_trading_at_limit_no_reminder() -> None:
    """日成交恰好等于阈值（5 笔）→ 不报警。"""
    day = datetime(2024, 1, 5)
    trades = [
        _buy(f"00000{i}", day.replace(hour=9 + i, minute=30), 10.0 + i)
        for i in range(5)
    ]
    res = SelfAudit(frequent_trades_per_day=5).audit(trades)
    assert not any(r.kind == "frequent_trading" for r in res.reminders)


# ---------------------------------------------------------------------------
# 5. small_sample
# ---------------------------------------------------------------------------


def test_small_sample_flag() -> None:
    """trades < 30 → small_sample=True 降级标注。"""
    trades = [
        _buy("600519", datetime(2024, 1, i + 1, 10, 0), 10.0) for i in range(5)
    ]
    res = SelfAudit(small_sample_threshold=30).audit(trades)
    assert res.small_sample is True
    assert res.n_trades == 5


def test_not_small_sample() -> None:
    """trades >= 30 → small_sample=False。"""
    trades = [
        _buy("600519", datetime(2024, 1, (i % 28) + 1, 10, 0), 10.0)
        for i in range(30)
    ]
    res = SelfAudit(small_sample_threshold=30).audit(trades)
    assert res.small_sample is False
    assert res.n_trades == 30


# ---------------------------------------------------------------------------
# 6. normal trades — no reminder
# ---------------------------------------------------------------------------


def test_normal_trades_no_reminder() -> None:
    """正常交易无任何提醒。买在低点、卖微盈、持仓短、笔数少。"""
    buy = _buy("600519", datetime(2024, 1, 5, 9, 35), 9.00)
    sell = _sell(
        "600519", datetime(2024, 1, 10, 14, 30), 10.00, realized_pnl=100.0
    )
    day_highs = {("600519", datetime(2024, 1, 5).date()): 10.50}
    res = SelfAudit().audit([buy, sell], day_highs=day_highs)
    assert res.reminders == []


# ---------------------------------------------------------------------------
# 7. multiple reminders collected
# ---------------------------------------------------------------------------


def test_multiple_reminders_collected() -> None:
    """同一组交易触发多种提醒 → reminders 收集多条。

    构造：
    - 追高：当日高 10.00，买 9.80（2%）
    - 割肉：成本 10.00，卖 9.00（亏 10%）
    - 持仓过久：buy→sell 间隔 > 60 天
    - 频繁：buy 当日共 6 笔（>5）
    - small_sample：trades=7 < 30
    """
    base_day = datetime(2024, 1, 5)
    # buy 日 6 笔 → 触发 frequent_trading；sell 在 80 天后触发过久+割肉
    buy_main = _buy("600519", base_day.replace(hour=14, minute=30), 9.80)
    buy2 = _buy("000001", base_day.replace(hour=9, minute=35), 8.0)
    buy3 = _buy("000002", base_day.replace(hour=10, minute=0), 8.0)
    buy4 = _buy("000003", base_day.replace(hour=10, minute=30), 8.0)
    buy5 = _buy("000004", base_day.replace(hour=11, minute=0), 8.0)
    buy6 = _buy("000005", base_day.replace(hour=13, minute=0), 8.0)
    sell_main = _sell(
        "600519",
        base_day + timedelta(days=80),
        9.00,
        realized_pnl=-100.0,
    )
    day_highs = {("600519", base_day.date()): 10.00}
    trades = [buy_main, buy2, buy3, buy4, buy5, buy6, sell_main]
    res = SelfAudit(
        chase_threshold=0.05,
        loss_cut_threshold=-0.08,
        holding_days_too_long=60,
        frequent_trades_per_day=5,
        small_sample_threshold=30,
    ).audit(trades, day_highs=day_highs)
    kinds = {r.kind for r in res.reminders}
    # 4 类提醒应全部命中
    assert "chasing_high" in kinds
    assert "cutting_loss" in kinds
    assert "holding_too_long" in kinds
    assert "frequent_trading" in kinds
    # 小样本降级标注
    assert res.small_sample is True
    assert res.n_trades == 7


# ---------------------------------------------------------------------------
# SelfAuditResult / Reminder 基础字段
# ---------------------------------------------------------------------------


def test_self_audit_result_defaults() -> None:
    """SelfAuditResult 默认值：reminders=[], n_trades=0, small_sample=False。"""
    r = SelfAuditResult()
    assert r.reminders == []
    assert r.n_trades == 0
    assert r.small_sample is False


def test_reminder_fields() -> None:
    """Reminder 字段：kind / symbol / detail / severity（默认 info）。"""
    r = Reminder(kind="chasing_high", symbol="600519", detail="test")
    assert r.kind == "chasing_high"
    assert r.symbol == "600519"
    assert r.detail == "test"
    assert r.severity == "info"
