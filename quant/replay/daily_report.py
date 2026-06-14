"""每日复盘报告（M5a §4.8.3 Task 7）。

将当日信号表现、预期 vs 实际偏差、买卖点质量与情绪/资金/龙虎榜事件
归集为 DailyReportData，并支持落 audit_event 归档（kind='daily_report'）。
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# 数据载体
# ---------------------------------------------------------------------------


@dataclass
class SignalPerformance:
    """信号命中率统计。"""

    total: int
    hit: int
    hit_rate: float          # hit/total
    avg_strength: float      # mean(|strength|)


@dataclass
class DeviationAttribution:
    """预期/实际盈亏偏差归因。"""

    expected_pnl: float
    actual_pnl: float
    deviation: float         # actual - expected
    factors: dict = field(default_factory=dict)


@dataclass
class TradePointQuality:
    """买卖点质量评分（0-1）。"""

    buy_score: float
    sell_score: float


@dataclass
class DailyReportData:
    """每日复盘报告。"""

    report_date: _dt.date
    signal_perf: SignalPerformance
    deviation: DeviationAttribution
    trade_quality: TradePointQuality
    events: list = field(default_factory=list)
    var_95: Optional[float] = None
    var_99: Optional[float] = None
    archived: bool = False


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _symbol_of(item: Any) -> Optional[str]:
    """从 Signal/命名元组/字符串中提取 symbol；不可识别返回 None。"""
    if isinstance(item, str):
        return item
    return getattr(item, "symbol", None)


def _direction_of(item: Any) -> Optional[int]:
    """提取 direction（+1 多 / -1 空）；不可识别返回 None。"""
    return getattr(item, "direction", None)


# ---------------------------------------------------------------------------
# 构造器
# ---------------------------------------------------------------------------


def build_signal_performance(
    signals: Iterable[Any], realized_returns: dict
) -> SignalPerformance:
    """信号命中率与平均强度。

    hit = 信号方向与实际收益方向一致（buy&return>0 或 sell&return<0）。
    缺失 realized_returns 的标的不计入命中，但强度仍计入均值。
    """
    signals = list(signals)
    total = len(signals)
    if total == 0:
        return SignalPerformance(0, 0, 0.0, 0.0)

    hit = 0
    strength_sum = 0.0
    for sig in signals:
        strength_sum += abs(getattr(sig, "strength", 0.0))
        symbol = _symbol_of(sig)
        direction = _direction_of(sig)
        if symbol is None or direction is None or symbol not in realized_returns:
            continue
        ret = realized_returns[symbol]
        if (direction > 0 and ret > 0) or (direction < 0 and ret < 0):
            hit += 1

    return SignalPerformance(
        total=total,
        hit=hit,
        hit_rate=hit / total,
        avg_strength=strength_sum / total,
    )


def build_deviation(
    expected_pnl: float,
    actual_pnl: float,
    factors: Optional[dict] = None,
) -> DeviationAttribution:
    """偏差 = actual - expected；factors 透传。"""
    return DeviationAttribution(
        expected_pnl=expected_pnl,
        actual_pnl=actual_pnl,
        deviation=actual_pnl - expected_pnl,
        factors=dict(factors) if factors else {},
    )


def build_trade_quality(
    buys: Iterable[Any], sells: Iterable[Any], realized_returns: dict
) -> TradePointQuality:
    """买卖点质量评分（0-1）。

    buy_score = 买入信号中实现正收益的比例（买后涨=高分）。
    sell_score = 卖出信号对应标的实际下跌的比例（卖后跌=避开亏损=高分）。
    """
    buys = list(buys)
    sells = list(sells)

    buy_score = _positive_ratio(buys, realized_returns, positive=True)
    sell_score = _positive_ratio(sells, realized_returns, positive=False)
    return TradePointQuality(buy_score=buy_score, sell_score=sell_score)


def _positive_ratio(
    items: list, realized_returns: dict, positive: bool
) -> float:
    """命中的比例：positive=True 计算 return>0 的占比，否则 return<0。"""
    n = len(items)
    if n == 0:
        return 0.0
    matched = 0
    for it in items:
        symbol = _symbol_of(it)
        if symbol is None or symbol not in realized_returns:
            continue
        ret = realized_returns[symbol]
        if (positive and ret > 0) or (not positive and ret < 0):
            matched += 1
    return matched / n


# ---------------------------------------------------------------------------
# 组装与归档
# ---------------------------------------------------------------------------


def generate_daily_report(
    report_date: _dt.date,
    signals: Iterable[Any],
    realized_returns: dict,
    fills: Iterable[Any],
    expected_pnl: float,
    actual_pnl: float,
    events: Optional[list] = None,
    var_95: Optional[float] = None,
    var_99: Optional[float] = None,
    factors: Optional[dict] = None,
    store=None,
) -> DailyReportData:
    """组装 DailyReportData，store 非空时同步归档。"""
    signals = list(signals)
    buys = [s for s in signals if _direction_of(s) is not None and _direction_of(s) > 0]
    sells = [s for s in signals if _direction_of(s) is not None and _direction_of(s) < 0]

    report = DailyReportData(
        report_date=report_date,
        signal_perf=build_signal_performance(signals, realized_returns),
        deviation=build_deviation(expected_pnl, actual_pnl, factors=factors),
        trade_quality=build_trade_quality(buys, sells, realized_returns),
        events=list(events) if events else [],
        var_95=var_95,
        var_99=var_99,
    )

    if store is not None:
        archive_report(store, report)
        report.archived = True
    return report


def archive_report(store, report: DailyReportData) -> None:
    """落 audit_event(kind='daily_report', ref_id=date.isoformat(), payload=json)。"""
    payload = _serialize_report(report)
    store.execute(
        "INSERT INTO audit_event (ts, kind, ref_id, account_id, payload) "
        "VALUES (?, ?, ?, NULL, ?)",
        (int(time.time() * 1000), "daily_report", report.report_date.isoformat(), payload),
    )


def _serialize_report(report: DailyReportData) -> str:
    """将报告转为可序列化 dict 的 JSON（date → ISO 字符串）。"""
    data = asdict(report)
    data["report_date"] = report.report_date.isoformat()
    return json.dumps(data, ensure_ascii=False, default=str)
