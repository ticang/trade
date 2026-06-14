"""PIT（point-in-time）工具：推断外部事实的 available_at 与置信度标记。

依据 v0.5 §4.1.5：每条外部事实带 available_at；实时段可证（live），
回填段规则推断（rule_inferred）。因子物化 available_at 取依赖字段 available_at 的 max。
"""

from datetime import date, datetime, time, timedelta
from typing import Iterable, Literal

PitConfidence = Literal["live", "rule_inferred"]

# 数据集与收盘后披露时刻映射（§4.1.5）
_DATASET_TIME = {
    "daily_ohlc": time(15, 0),
    "longhubang": time(18, 0),
}


def pit_confidence_for(live: bool) -> PitConfidence:
    """根据实时标志返回置信度标记。"""
    return "live" if live else "rule_inferred"


def derive_available_at(
    dataset: str,
    trade_date: date,
    *,
    live: bool,
    disclose_at: date | None = None,
) -> datetime:
    """推断单条事实的 available_at 时刻。

    dataset ∈ {"daily_ohlc","longhubang","margin","financial"}。
    daily_ohlc→T 日 15:00；longhubang→T 日 18:00；margin→T+1 日 00:00；
    financial→披露日 00:00（未提供 disclose_at 抛 NotImplementedError）。
    未知 dataset 抛 ValueError。

    注意：live 仅影响调用方另取的 pit_confidence，不影响本函数返回时刻。
    """
    _ = live  # live 不影响时刻，仅作语义占位
    if dataset in _DATASET_TIME:
        return datetime.combine(trade_date, _DATASET_TIME[dataset])
    if dataset == "margin":
        # 融资融券 T+1 日 00:00（§4.1.5 简化为 trade_date+1 day）
        return datetime.combine(trade_date + timedelta(days=1), time(0, 0))
    if dataset == "financial":
        # 财报以披露日为准，未提供则无法推断
        if disclose_at is None:
            raise NotImplementedError("financial dataset requires disclose_at")
        return datetime.combine(disclose_at, time(0, 0))
    raise ValueError(f"unknown dataset: {dataset}")


def max_available_at(deps: Iterable[datetime]) -> datetime:
    """因子 available_at 取依赖字段 available_at 的 max；空序列抛 ValueError。"""
    iterator = iter(deps)
    try:
        latest = next(iterator)
    except StopIteration:
        raise ValueError("empty dependency sequence")
    for dep in iterator:
        if dep > latest:
            latest = dep
    return latest
