"""数据质量验证层：deny-default 拦截脏数据。

生产者只采集，把关者独立校验。未知 dataset 默认拒绝，脏数据不进因子引擎。
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Verdict(Enum):
    PASS = "pass"
    DENY = "deny"


@dataclass
class Result:
    decision: Verdict
    reason: str = ""


# bar 校验所需关键字段
_BAR_FIELDS = ("open", "high", "low", "close", "volume")


class DataQualityGate:
    def validate(self, dataset: str, record: dict) -> Result:
        # 按数据集分派；未知 dataset 默认拒绝
        if dataset == "bar":
            return self.validate_bar(record)
        return Result(Verdict.DENY, "unknown dataset")

    def validate_bar(self, bar: dict) -> Result:
        # 关键字段缺失或 None → DENY
        for field in _BAR_FIELDS:
            if field not in bar or bar[field] is None:
                return Result(Verdict.DENY, f"missing {field}")

        o, h, l, c, v = bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]

        # 负值校验
        if any(x < 0 for x in (o, h, l, c, v)):
            return Result(Verdict.DENY, "negative value")

        # OHLC 一致性
        if h < max(o, c, l) or l > min(o, c, h) or h < l:
            return Result(Verdict.DENY, "ohlc inconsistent")

        return Result(Verdict.PASS)

    def validate_bars_cross_section(
        self,
        bars: list[dict],
        field: str = "close",
        z_threshold: float = 5.0,
    ) -> list[Result]:
        # 样本不足无法算 z，全部通过
        if len(bars) < 2:
            return [Result(Verdict.PASS) for _ in bars]

        values = np.array([b[field] for b in bars], dtype=float)
        mean = values.mean()
        std = values.std()

        results: list[Result] = []
        for x in values:
            # std=0 时所有值相同，无离群
            z = 0.0 if std == 0 else (x - mean) / std
            if abs(z) > z_threshold:
                results.append(Result(Verdict.DENY, f"outlier z={z:.2f}"))
            else:
                results.append(Result(Verdict.PASS))
        return results
