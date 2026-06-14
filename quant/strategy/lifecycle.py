"""策略生命周期状态机（§4.4.4）。

状态机：draft → backtested → paper → approved → live → monitoring → degraded → offline。
上线门禁：回测指标达标（ic >= 0.03）方可进入 APPROVED；在线监控衰减则降级/下线。
"""
from dataclasses import dataclass, field
from enum import Enum

# IC 门禁阈值
_GATE_MIN_IC = 0.03
# 衰减阈值
_DEGRADE_DRAWDOWN = -0.15
_DEGRADE_IC = 0.015


class StrategyStatus(str, Enum):
    """策略生命周期状态。"""

    DRAFT = "draft"
    BACKTESTED = "backtested"
    PAPER = "paper"
    APPROVED = "approved"
    LIVE = "live"
    MONITORING = "monitoring"
    DEGRADED = "degraded"
    OFFLINE = "offline"


# 合法迁移图（有向）
_TRANSITIONS: dict[StrategyStatus, set[StrategyStatus]] = {
    StrategyStatus.DRAFT: {StrategyStatus.BACKTESTED},
    StrategyStatus.BACKTESTED: {
        StrategyStatus.PAPER,
        StrategyStatus.APPROVED,
        StrategyStatus.OFFLINE,
    },
    StrategyStatus.PAPER: {StrategyStatus.APPROVED, StrategyStatus.OFFLINE},
    StrategyStatus.APPROVED: {StrategyStatus.LIVE, StrategyStatus.OFFLINE},
    StrategyStatus.LIVE: {StrategyStatus.MONITORING, StrategyStatus.OFFLINE},
    StrategyStatus.MONITORING: {StrategyStatus.DEGRADED, StrategyStatus.OFFLINE},
    # 修复后可回 monitoring
    StrategyStatus.DEGRADED: {StrategyStatus.OFFLINE, StrategyStatus.MONITORING},
    StrategyStatus.OFFLINE: set(),  # 终态
}

# 进入 APPROVED 需门禁的前置状态
_GATE_SOURCES = {StrategyStatus.BACKTESTED, StrategyStatus.PAPER}


def _passes_gate(metrics: dict) -> bool:
    """门禁：ic 达标（>= 0.03）。"""

    return metrics.get("ic", 0.0) >= _GATE_MIN_IC


@dataclass
class StrategyLifecycle:
    """策略生命周期：状态机 + 门禁 + 衰减检测。"""

    strategy: str
    status: StrategyStatus = StrategyStatus.DRAFT
    approved: bool = False  # 人审/门禁标记
    metrics: dict = field(default_factory=dict)  # {ic, turnover, drawdown}

    def can_transition(self, to: StrategyStatus) -> bool:
        return to in _TRANSITIONS.get(self.status, set())

    def transition(self, to: StrategyStatus, *, metrics_check: bool = True) -> StrategyStatus:
        """迁移。非法迁移抛 ValueError。

        进入 APPROVED 时校验门禁（ic 达标）；通过后置 approved=True。
        """

        if not self.can_transition(to):
            raise ValueError(
                f"非法迁移: {self.status.value} -> {to.value}"
            )

        # 门禁：BACKTESTED/PAPER → APPROVED
        if metrics_check and self.status in _GATE_SOURCES and to is StrategyStatus.APPROVED:
            if not _passes_gate(self.metrics):
                raise ValueError("gate failed: metrics 不达标")

        self.status = to
        if to is StrategyStatus.APPROVED:
            self.approved = True
        return self.status

    def check_degradation(self) -> StrategyStatus | None:
        """监控期衰减检测：drawdown<-0.15 或 ic<0.015 → 返回 DEGRADED。"""

        if self.status is not StrategyStatus.MONITORING:
            return None
        drawdown = self.metrics.get("drawdown", 0.0)
        ic = self.metrics.get("ic", float("inf"))
        if drawdown < _DEGRADE_DRAWDOWN or ic < _DEGRADE_IC:
            return StrategyStatus.DEGRADED
        return None
