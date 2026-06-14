"""每日复盘报告测试（M5a §4.8.3 Task 7）。

校验信号表现、预期/实际偏差归因、买卖点质量评分、事件回放与归档落库。

TDD：本文件先于 daily_report.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.replay.daily_report import (
    DailyReportData,
    SignalPerformance,
    DeviationAttribution,
    TradePointQuality,
    archive_report,
    build_deviation,
    build_signal_performance,
    build_trade_quality,
    generate_daily_report,
)


# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------


def _sig(symbol: str, direction: int, strength: float) -> SimpleNamespace:
    """轻量 Signal 替身：含 symbol/direction/strength。"""
    return SimpleNamespace(symbol=symbol, direction=direction, strength=strength)


def _store(tmp_path):
    """起停一个 SqliteStore，用例结束回收写线程。"""
    s = SqliteStore(str(tmp_path / "replay.db"))
    s.start()
    yield s
    s.stop()


# ---------------------------------------------------------------------------
# SignalPerformance
# ---------------------------------------------------------------------------


def test_signal_performance_hit_rate():
    """3 信号中 2 个方向与实际收益一致 → hit_rate=2/3。"""
    signals = [
        _sig("000001", +1, 0.5),   # 多 + 实际涨 → 命中
        _sig("000002", +1, 0.4),   # 多 + 实际跌 → 未命中
        _sig("000003", -1, 0.6),   # 空 + 实际跌 → 命中
    ]
    realized = {"000001": 0.02, "000002": -0.01, "000003": -0.03}
    perf = build_signal_performance(signals, realized)
    assert isinstance(perf, SignalPerformance)
    assert perf.total == 3
    assert perf.hit == 2
    assert perf.hit_rate == pytest.approx(2 / 3, rel=1e-9)


def test_signal_avg_strength():
    """avg_strength = mean(|strength|)。"""
    signals = [_sig("A", +1, 0.4), _sig("B", -1, -0.6), _sig("C", +1, 0.2)]
    perf = build_signal_performance(signals, {})
    assert perf.avg_strength == pytest.approx((0.4 + 0.6 + 0.2) / 3, abs=1e-9)


def test_signal_performance_empty():
    """空信号列表应安全返回零值，避免除零。"""
    perf = build_signal_performance([], {})
    assert perf.total == 0
    assert perf.hit == 0
    assert perf.hit_rate == 0.0
    assert perf.avg_strength == 0.0


# ---------------------------------------------------------------------------
# DeviationAttribution
# ---------------------------------------------------------------------------


def test_deviation_calc():
    """expected=100, actual=80 → deviation=actual-expected=-20。"""
    dev = build_deviation(100.0, 80.0)
    assert isinstance(dev, DeviationAttribution)
    assert dev.expected_pnl == 100.0
    assert dev.actual_pnl == 80.0
    assert dev.deviation == pytest.approx(-20.0)
    assert dev.factors == {}


def test_deviation_with_factors():
    """factors dict 透传。"""
    factors = {"slippage": -5.0, "fee": -3.0}
    dev = build_deviation(100.0, 92.0, factors=factors)
    assert dev.deviation == pytest.approx(-8.0)
    assert dev.factors == factors


# ---------------------------------------------------------------------------
# TradePointQuality
# ---------------------------------------------------------------------------


def test_trade_quality_scores():
    """买入信号中实现正收益比例 → buy_score；卖出后下跌比例 → sell_score。"""
    buys = [_sig("B1", +1, 0.5), _sig("B2", +1, 0.4), _sig("B3", +1, 0.3)]
    sells = [_sig("S1", -1, 0.5), _sig("S2", -1, 0.4)]
    realized = {"B1": 0.02, "B2": -0.01, "B3": 0.05, "S1": -0.02, "S2": 0.01}
    q = build_trade_quality(buys, sells, realized)
    assert isinstance(q, TradePointQuality)
    # 3 买中 2 正 → 2/3
    assert q.buy_score == pytest.approx(2 / 3, rel=1e-9)
    # 2 卖中 1 跌 → 1/2
    assert q.sell_score == pytest.approx(1 / 2, rel=1e-9)


def test_trade_quality_empty():
    """无买卖信号 → 0 分（不除零）。"""
    q = build_trade_quality([], [], {})
    assert q.buy_score == 0.0
    assert q.sell_score == 0.0


def test_trade_quality_range():
    """评分应落在 [0, 1]。"""
    buys = [_sig("B1", +1, 0.5)]
    sells = [_sig("S1", -1, 0.5)]
    realized = {"B1": 0.02, "S1": -0.02}
    q = build_trade_quality(buys, sells, realized)
    assert 0.0 <= q.buy_score <= 1.0
    assert 0.0 <= q.sell_score <= 1.0


# ---------------------------------------------------------------------------
# generate_daily_report
# ---------------------------------------------------------------------------


def test_generate_report_assembles():
    """generate 返回 DailyReportData，字段齐备。"""
    today = _dt.date(2024, 1, 5)
    signals = [_sig("000001", +1, 0.5), _sig("000002", -1, 0.4)]
    realized = {"000001": 0.02, "000002": -0.01}
    fills = []
    report = generate_daily_report(
        report_date=today,
        signals=signals,
        realized_returns=realized,
        fills=fills,
        expected_pnl=100.0,
        actual_pnl=92.0,
        var_95=1500.0,
        var_99=2300.0,
    )
    assert isinstance(report, DailyReportData)
    assert report.report_date == today
    assert isinstance(report.signal_perf, SignalPerformance)
    assert isinstance(report.deviation, DeviationAttribution)
    assert isinstance(report.trade_quality, TradePointQuality)
    assert report.deviation.deviation == pytest.approx(-8.0)
    assert report.var_95 == 1500.0
    assert report.var_99 == 2300.0
    assert report.events == []
    assert report.archived is False


def test_events_replay():
    """events list 透传进报告。"""
    today = _dt.date(2024, 1, 5)
    events = [
        {"kind": "sentiment", "note": "市场情绪偏强"},
        {"kind": "capital", "note": "北向净流入 10 亿"},
        {"kind": "lhb", "note": "龙虎榜活跃"},
    ]
    report = generate_daily_report(
        report_date=today,
        signals=[],
        realized_returns={},
        fills=[],
        expected_pnl=0.0,
        actual_pnl=0.0,
        events=events,
    )
    assert report.events == events


def test_generate_with_factors():
    """generate 支持透传 factors 到偏差归因。"""
    today = _dt.date(2024, 1, 5)
    factors = {"slippage": -5.0}
    report = generate_daily_report(
        report_date=today,
        signals=[],
        realized_returns={},
        fills=[],
        expected_pnl=100.0,
        actual_pnl=95.0,
        factors=factors,
    )
    assert report.deviation.factors == factors


# ---------------------------------------------------------------------------
# 归档落库
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    yield from _store(tmp_path)


def test_archive_to_store(store):
    """archive_report → audit_event 落一行 kind='daily_report'。"""
    today = _dt.date(2024, 1, 5)
    report = DailyReportData(
        report_date=today,
        signal_perf=SignalPerformance(1, 1, 1.0, 0.5),
        deviation=DeviationAttribution(100.0, 80.0, -20.0),
        trade_quality=TradePointQuality(0.7, 0.6),
        events=[{"kind": "lhb", "note": "x"}],
    )
    archive_report(store, report)
    store.flush()

    row = store.query_one(
        "SELECT kind, ref_id, payload FROM audit_event WHERE kind = ?",
        ("daily_report",),
    )
    assert row is not None
    assert row["kind"] == "daily_report"
    assert row["ref_id"] == today.isoformat()
    assert "report_date" in row["payload"]
    assert "signal_perf" in row["payload"]


def test_generate_with_store_archived(store):
    """generate(store=...) → 归档并返回 archived=True。"""
    today = _dt.date(2024, 1, 5)
    report = generate_daily_report(
        report_date=today,
        signals=[_sig("000001", +1, 0.5)],
        realized_returns={"000001": 0.02},
        fills=[],
        expected_pnl=100.0,
        actual_pnl=110.0,
        store=store,
    )
    assert report.archived is True
    store.flush()
    row = store.query_one(
        "SELECT kind, ref_id FROM audit_event WHERE kind = ?",
        ("daily_report",),
    )
    assert row is not None
    assert row["ref_id"] == today.isoformat()
