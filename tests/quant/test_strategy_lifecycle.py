"""策略生命周期状态机测试（§4.4.4）。

覆盖：合法迁移图、门禁、衰减检测、全路径、终态。
"""
import pytest

from quant.strategy.lifecycle import StrategyLifecycle, StrategyStatus


def test_initial_status_draft():
    lc = StrategyLifecycle(strategy="s1")
    assert lc.status is StrategyStatus.DRAFT


def test_legal_transition():
    lc = StrategyLifecycle(strategy="s1")
    new = lc.transition(StrategyStatus.BACKTESTED)
    assert new is StrategyStatus.BACKTESTED
    assert lc.status is StrategyStatus.BACKTESTED


def test_illegal_transition_raises():
    lc = StrategyLifecycle(strategy="s1")  # DRAFT
    with pytest.raises(ValueError):
        lc.transition(StrategyStatus.LIVE)


def test_offline_terminal():
    lc = StrategyLifecycle(strategy="s1", status=StrategyStatus.OFFLINE)
    for target in StrategyStatus:
        with pytest.raises(ValueError):
            lc.transition(target)


def test_approval_gate_backtested_to_approved():
    # 达标
    lc = StrategyLifecycle(strategy="s1", status=StrategyStatus.BACKTESTED, metrics={"ic": 0.05})
    assert lc.transition(StrategyStatus.APPROVED) is StrategyStatus.APPROVED
    assert lc.approved is True

    # ic 不达标
    lc_bad = StrategyLifecycle(strategy="s1", status=StrategyStatus.BACKTESTED, metrics={"ic": 0.01})
    with pytest.raises(ValueError, match="gate"):
        lc_bad.transition(StrategyStatus.APPROVED)

    # 无 metrics
    lc_none = StrategyLifecycle(strategy="s1", status=StrategyStatus.BACKTESTED)
    with pytest.raises(ValueError, match="gate"):
        lc_none.transition(StrategyStatus.APPROVED)


def test_full_lifecycle_path():
    lc = StrategyLifecycle(strategy="s1")
    path = [
        StrategyStatus.BACKTESTED,
        StrategyStatus.PAPER,
        StrategyStatus.APPROVED,
        StrategyStatus.LIVE,
        StrategyStatus.MONITORING,
        StrategyStatus.DEGRADED,
        StrategyStatus.OFFLINE,
    ]
    # 进入 APPROVED 需 metrics，提前注入
    lc.metrics = {"ic": 0.05}
    for nxt in path:
        assert lc.transition(nxt) is nxt
    assert lc.status is StrategyStatus.OFFLINE


def test_degradation_detection():
    # 衰减
    lc = StrategyLifecycle(
        strategy="s1",
        status=StrategyStatus.MONITORING,
        metrics={"drawdown": -0.20},
    )
    assert lc.check_degradation() is StrategyStatus.DEGRADED

    # 未衰减
    lc_ok = StrategyLifecycle(
        strategy="s1",
        status=StrategyStatus.MONITORING,
        metrics={"drawdown": -0.05},
    )
    assert lc_ok.check_degradation() is None


def test_degraded_can_remonitor():
    # 修复后回 monitoring
    lc = StrategyLifecycle(strategy="s1", status=StrategyStatus.DEGRADED)
    assert lc.transition(StrategyStatus.MONITORING) is StrategyStatus.MONITORING

    # 也可下线
    lc2 = StrategyLifecycle(strategy="s1", status=StrategyStatus.DEGRADED)
    assert lc2.transition(StrategyStatus.OFFLINE) is StrategyStatus.OFFLINE


def test_paper_to_approved_needs_metrics():
    lc = StrategyLifecycle(strategy="s1", status=StrategyStatus.PAPER, metrics={"ic": 0.04})
    assert lc.transition(StrategyStatus.APPROVED) is StrategyStatus.APPROVED
    assert lc.approved is True
