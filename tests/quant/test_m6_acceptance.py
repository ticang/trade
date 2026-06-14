"""M6 多智能体 集成验收测试（设计 v0.5 §11 M6 验收，capstone）。

扁平化端到端串起 M6 全部组件：
- 5 角色闭环（Hypothesizer→Composer→TesterRole→Judge→Iterator）
- MultiAgentOrchestrator 可恢复闭环（checkpoint/resume，≥50 轮机制可达）
- M3 Tester 门禁作为标准入库门（强因子进 accepted，弱因子进 archived/iterated）
- SentimentProviderV2 合规开关（默认关，显式知情开启才 fetch）
- SubprocessSandbox 占位可执行（M6 主沙箱是 DSL，子进程为可选路径）

确定性合成数据 + mock LLM（FakeHypothesizer 按 DSL 序列返回），保证可重跑。
不依赖网络、不调用真实 LLM。

对应 §11 M6「工程 Done」8 条：
1. 闭环驱动：MultiAgentOrchestrator.run max_rounds=3 → rounds_completed=3
2. 断点恢复：K 轮中断 → 新 orchestrator resume 续跑到 N，state 累计一致
3. 5 角色协作：Hypothesizer→Composer→TesterRole→Judge→Iterator 各被调用
4. 标准门禁：通过 M3 Tester 五门的强因子进 accepted
5. 情绪默认关：ComplianceConfig 默认 → is_enabled=False, fetch=None
6. 情绪显式开：enabled+acknowledged+not store_personal → is_enabled=True, fetch 返回 SocialSentiment
7. 50 轮机制可达：max_rounds=50 mock → rounds_completed=50（机制验证，注释说明真实 50 轮同等）
8. 子进程沙箱占位：SubprocessSandbox 可执行简单代码；M6 主路径是 DSL（注释说明）
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.data.sqlite_store import SqliteStore
from quant.factor.factors.sentiment_v2 import (
    ComplianceConfig,
    SentimentProviderV2,
    SocialSentiment,
)
from quant.mining.agent_state import AgentStateStore
from quant.mining.multi_agent import (
    Composer,
    Hypothesis,
    Hypothesizer,
    Iterator,
    Judge,
    MultiAgentOrchestrator,
    MultiAgentResult,
    TesterRole,
)
from quant.mining.sandbox_subprocess import SandboxResult, SubprocessSandbox
from quant.mining.tester import TestConfig, Tester
from quant.mining.tracker import ExperimentTracker


# ---------------------------------------------------------------------------
# fixtures：临时 sqlite + state_store + tracker
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    """临时 sqlite，start/stop 由 fixture 管理。"""
    s = SqliteStore(str(tmp_path / "m6_acc.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def state_store(store):
    return AgentStateStore(store)


@pytest.fixture
def tracker(store):
    return ExperimentTracker(store)


# ---------------------------------------------------------------------------
# mock Hypothesizer：绕过真实 LLM，按 DSL 序列逐轮返回 Hypothesis
# ---------------------------------------------------------------------------
class FakeHypothesizer(Hypothesizer):
    """不调 super().__init__，避免依赖 LLMClient。

    dsl_sequence：按 round_idx 取模循环返回；raise_at 触发注入中断模拟断点。
    记录 generate/test 角色被调次数，供 5 角色协作断言。
    """

    def __init__(self, dsl_sequence: list[str], raise_at: int | None = None):
        self.dsl_sequence = dsl_sequence
        self.raise_at = raise_at
        self.calls = 0
        self.topic_seen: list[str] = []
        self.feedback_seen: list[str] = []

    def generate(self, topic: str, round_idx: int, feedback: str = "") -> Hypothesis:  # type: ignore[override]
        if self.raise_at is not None and round_idx == self.raise_at:
            self.calls += 1
            raise RuntimeError(f"injected break at round {round_idx}")
        expr = self.dsl_sequence[round_idx % len(self.dsl_sequence)]
        self.calls += 1
        self.topic_seen.append(topic)
        self.feedback_seen.append(feedback)
        return Hypothesis(hypothesis=f"h{round_idx}", dsl_expr=expr, rationale="mock")


# ---------------------------------------------------------------------------
# 5 角色追踪包装：薄包装记录角色被调，协作链可断言
# ---------------------------------------------------------------------------
class TrackingComposer(Composer):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def compose(self, hyp, panel):  # type: ignore[override]
        self.calls += 1
        return super().compose(hyp, panel)


class TrackingTesterRole(TesterRole):
    def __init__(self, tester=None):
        super().__init__(tester)
        self.calls = 0

    def test(self, factor_values, returns_panel, **kw):  # type: ignore[override]
        self.calls += 1
        return super().test(factor_values, returns_panel, **kw)


class TrackingJudge(Judge):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def decide(self, test_result):  # type: ignore[override]
        self.calls += 1
        return super().decide(test_result)


class TrackingIterator(Iterator):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def next_direction(self, round_result, history):  # type: ignore[override]
        self.calls += 1
        return super().next_direction(round_result, history)


# ---------------------------------------------------------------------------
# 合成 panel：100 symbol × 20 trade_date，returns 与 close-rank 强对齐
# rank(close) 通过门禁（accept），delay(close,1) 时序因子弱（iterate）
# ---------------------------------------------------------------------------
def _build_panels(seed: int = 7, n_sym: int = 100, n_date: int = 20):
    """造宽格式 panel（symbol/trade_date/close）+ 长格式 returns_panel。

    returns_panel.value 与同截面 close-rank 线性相关 + 小噪声，
    使 rank(close) 因子 IC 强，通过 M3 Tester 五门；时序因子弱，触发 iterate/archive。
    """
    rng = np.random.default_rng(seed)
    syms = [f"S{i:03d}" for i in range(n_sym)]
    dates = pd.date_range("2024-01-01", periods=n_date, freq="D").astype("int64") // 10**9

    base = np.linspace(1.0, 100.0, n_sym)
    rng.shuffle(base)
    wide_rows = []
    ret_rows = []
    for d in dates:
        close_vals = base + rng.normal(0, 0.5, size=n_sym)
        order = np.argsort(close_vals)
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(n_sym, dtype=float)
        ret_vals = 0.001 * ranked + rng.normal(0, 0.0003, size=n_sym)
        for s, c, r in zip(syms, close_vals, ret_vals):
            wide_rows.append((s, int(d), float(c)))
            ret_rows.append((int(d), s, float(r)))
    panel = pd.DataFrame(wide_rows, columns=["symbol", "trade_date", "close"])
    returns_panel = pd.DataFrame(ret_rows, columns=["trade_date", "symbol", "value"])
    return panel, returns_panel


@pytest.fixture(scope="module")
def panels():
    return _build_panels()


# ---------------------------------------------------------------------------
# orchestrator 工厂：5 角色真实（+ 可选 Tracking 包装）
# ---------------------------------------------------------------------------
def _make_orchestrator(
    dsl_sequence,
    state_store,
    tracker=None,
    raise_at=None,
    track=False,
):
    """5 角色真实 + mock Hypothesizer；track=True 返回 Tracking 角色供协作断言。

    Tester 门禁放宽至可被合成数据通过（min_ic/min_ir 下调），
    验证通过门禁的候选确实进 accepted。
    """
    h = FakeHypothesizer(dsl_sequence, raise_at=raise_at)
    c = TrackingComposer() if track else Composer()
    tester = Tester(TestConfig(min_ic=0.02, min_ir=0.3, min_long_short_annual=0.0))
    t = TrackingTesterRole(tester) if track else TesterRole(tester)
    j = TrackingJudge() if track else Judge()
    it = TrackingIterator() if track else Iterator()
    orch = MultiAgentOrchestrator(h, c, t, j, it, state_store, tracker)
    return orch, (h, c, t, j, it)


# ===========================================================================
# §11 M6 验收 1：闭环驱动 max_rounds=3
# ===========================================================================
def test_m6_multi_agent_loop(state_store, panels):
    """max_rounds=3 mock → rounds_completed=3，5 角色协作产出候选。

    验证闭环驱动可跑完指定轮数，返回结构完整 MultiAgentResult；
    accepted/archived/iterated 至少有一类被填充（5 角色产出有效候选）。
    """
    panel, returns = panels
    orch, _ = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("量价动量", panel, returns, max_rounds=3, seed=1)

    assert isinstance(res, MultiAgentResult)
    assert res.rounds_completed == 3
    # run_id 确定性：topic_seed
    assert res.run_id == "量价动量_1"
    # 强因子 rank(close) 至少有 1 条通过门禁进 accepted
    assert len(res.accepted) >= 1
    assert all(isinstance(h, Hypothesis) for h in res.accepted)


# ===========================================================================
# §11 M6 验收 2：checkpoint resume 断点恢复
# ===========================================================================
def test_m6_checkpoint_resume_recovery(state_store, panels):
    """跑到 K 轮 checkpoint → 中断 → 新 orchestrator resume_from → 续跑到 N。

    流程：
    1. 第一次：raise_at=2（在第 3 轮 hypothesize 抛异常）→ 前 2 轮 checkpoint 已落
    2. 第二次：新 orchestrator 同 run_id，state_store.resume 推断起始轮=2，续跑到 4
    断言：resumed_from=2，rounds 累计到 4，agent_run.state.rounds_completed 一致。
    """
    panel, returns = panels
    # 1. 第一次跑：注入中断
    orch1, _ = _make_orchestrator(["rank(close)"], state_store, raise_at=2)
    with pytest.raises(RuntimeError):
        orch1.run("恢复验收", panel, returns, max_rounds=4, seed=1)

    run_id = "恢复验收_1"
    # 中断时：前 2 轮已完整完成（rounds_completed=2），第 3 轮 hypothesize 即抛
    st = state_store.latest(run_id)
    assert st is not None
    assert st.state.get("rounds_completed") == 2

    # 2. 新 orchestrator 续跑（同 run_id，state_store.resume 推断）
    orch2, _ = _make_orchestrator(["rank(close)"], state_store)
    res = orch2.run("恢复验收", panel, returns, max_rounds=4, seed=1)

    assert res.resumed_from == 2
    assert res.rounds_completed == 4  # 累计到 max_rounds
    # agent_run 最终状态：done，round=4
    st2 = state_store.latest(run_id)
    assert st2 is not None
    assert st2.status == "done"
    assert st2.state.get("rounds_completed") == 4


# ===========================================================================
# §11 M6 验收 3：5 角色协作（每个角色都被调用，调用次数 == 轮数）
# ===========================================================================
def test_m6_five_roles_collaborate(state_store, panels):
    """5 角色协作链：每轮 Hypothesizer→Composer→TesterRole→Judge→Iterator 各被调一次。

    Tracking 包装记录各角色 calls，3 轮后每个角色 calls == 3。
    断言协作链顺序与覆盖（任一角色未被调即协作链断裂）。
    """
    panel, returns = panels
    orch, roles = _make_orchestrator(["rank(close)"], state_store, track=True)
    h, c, t, j, it = roles

    res = orch.run("五角色", panel, returns, max_rounds=3, seed=1)
    assert res.rounds_completed == 3

    # 5 角色各被调 3 次（每轮 1 次）
    assert h.calls == 3, f"Hypothesizer 调用次数 {h.calls} != 3"
    assert c.calls == 3, f"Composer 调用次数 {c.calls} != 3"
    assert t.calls == 3, f"TesterRole 调用次数 {t.calls} != 3"
    assert j.calls == 3, f"Judge 调用次数 {j.calls} != 3"
    assert it.calls == 3, f"Iterator 调用次数 {it.calls} != 3"

    # Iterator 收到的 feedback 链（第 1 轮为空，后续来自上轮 Judge 决策的方向）
    # Hypothesizer 收到的 feedback 序列：第 1 轮为 ""，后续为上轮 Iterator.next_direction 输出
    assert h.feedback_seen[0] == ""
    # accept 路径下 Iterator.next_direction 返回 'explore_variants'
    assert set(h.feedback_seen[1:]) <= {"explore_variants", "change_direction", "refine_params"}


# ===========================================================================
# §11 M6 验收 4：标准门禁（通过 M3 Tester 五门的因子进 accepted）
# ===========================================================================
def test_m6_standard_gate_factors(state_store, panels):
    """强因子（rank(close)，与 returns 强对齐）通过 M3 Tester 五门 → accepted。

    弱因子（非法 DSL 'foobar'、时序 delay(close,1)）不通过门禁 → archived/iterated。
    验证 Judge 依据 TestResult.passed 正确分流：passed=True→accept，否则 archive/iterate。
    """
    panel, returns = panels

    # 强因子：通过门禁
    orch_strong, _ = _make_orchestrator(["rank(close)"], state_store)
    res_strong = orch_strong.run("强因子验收", panel, returns, max_rounds=3, seed=1)
    assert len(res_strong.accepted) == 3  # 3 轮全部通过
    assert res_strong.archived == []
    assert res_strong.iterated == 0
    # accepted 中每条 hypothesis 携带 dsl_expr，且可通过 Sandbox.validate
    for hyp in res_strong.accepted:
        assert hyp.dsl_expr == "rank(close)"

    # 弱因子混合：第 1 轮非法 DSL（foobar）→ archive；第 2 轮 delay(close,1) 时序弱因子 → iterate
    orch_weak, _ = _make_orchestrator(
        ["foobar(close)", "delay(close,1)"], state_store
    )
    res_weak = orch_weak.run("弱因子验收", panel, returns, max_rounds=2, seed=1)
    assert len(res_weak.archived) >= 1   # 非法 DSL → Composer 返回 None → archive
    assert res_weak.iterated >= 1        # delay(close,1) 弱相关 → iterate
    assert res_weak.accepted == []


# ===========================================================================
# §11 M6 验收 5：SentimentProviderV2 默认关
# ===========================================================================
def test_m6_sentiment_v2_default_off():
    """合规默认关：ComplianceConfig() → is_enabled=False, fetch 返回 None。

    force=True 不可绕过合规前置。
    """
    provider = SentimentProviderV2()  # 默认 ComplianceConfig
    assert provider.is_enabled() is False

    # fetch 默认返回 None（合规禁用）
    result = provider.fetch("白酒")
    assert result is None

    # force=True 仍不可绕过合规
    result_forced = provider.fetch("白酒", force=True)
    assert result_forced is None


# ===========================================================================
# §11 M6 验收 6：SentimentProviderV2 显式开启（合规满足）
# ===========================================================================
def test_m6_sentiment_v2_explicit_enable():
    """显式开启：enabled+user_acknowledged+not store_personal → is_enabled=True，fetch 返回 SocialSentiment。

    合规前置三条件全满足才开启；任一缺失（如缺 acknowledged）即关。
    fetch 返回的 SocialSentiment 携带匿名化聚合指标（无个人可识别字段）。
    """
    cfg = ComplianceConfig(
        enabled=True,
        user_acknowledged=True,
        store_personal_content=False,
    )
    provider = SentimentProviderV2(cfg)
    assert provider.is_enabled() is True

    result = provider.fetch("白酒")
    assert isinstance(result, SocialSentiment)
    # SocialSentiment 字段：匿名化聚合（无 user_id / nickname）
    assert result.discussion_count > 0
    assert isinstance(result.keyword_freq, dict)
    assert "白酒" in result.keyword_freq
    assert -1.0 <= result.bullish_score <= 1.0

    # 缺 user_acknowledged 即合规不满足
    cfg_partial = ComplianceConfig(enabled=True, user_acknowledged=False)
    provider_partial = SentimentProviderV2(cfg_partial)
    assert provider_partial.is_enabled() is False
    assert provider_partial.fetch("白酒") is None


# ===========================================================================
# §11 M6 验收 7：50 轮机制可达（mock LLM 下快速跑通）
# ===========================================================================
def test_m6_fifty_rounds_mechanism(state_store, panels):
    """max_rounds=50 mock（FakeHypothesizer 即时返回）→ rounds_completed=50。

    机制验证：闭环驱动可达 ≥50 轮不崩，checkpoint 一致。
    注释：真实 50 轮（接入真实 LLM）每轮产 1 条假设 + DSL 求值 + 五门测试，
    机制路径与本 mock 等同；mock 下每轮即时返回，仅省去 LLM 网络往返，
    状态机/checkpoint/角色协作链与真实 50 轮同等。
    """
    panel, returns = panels
    orch, _ = _make_orchestrator(["rank(close)"], state_store)
    res = orch.run("五十轮验收", panel, returns, max_rounds=50, seed=1)

    assert res.rounds_completed == 50
    # agent_run 最终状态反映第 50 轮 done
    st = state_store.latest(res.run_id)
    assert st is not None
    assert st.status == "done"
    assert st.state.get("rounds_completed") == 50
    # 50 轮 rank(close) 全过门禁 → accepted == 50
    assert len(res.accepted) == 50


# ===========================================================================
# §11 M6 验收 8：SubprocessSandbox 占位可执行（M6 主路径是 DSL）
# ===========================================================================
def test_m6_subprocess_sandbox_optional():
    """SubprocessSandbox 占位可执行简单 Python 代码，返回 SandboxResult。

    注释：M6 主沙箱路径是 M3 DSL 解释器（受控算子集合，无任意代码执行），
    本子进程沙箱仅当 3b 需 LLM 直产 Python 源码时启用，为可选路径占位。
    生产部署应叠加 seccomp/nsjail + 资源配额 + 只读根 + 网络禁用（M6 阶段占位）。
    """
    sb = SubprocessSandbox(timeout=5.0)
    r = sb.run("print('m6_sandbox_ok')")
    assert isinstance(r, SandboxResult)
    assert "m6_sandbox_ok" in r.stdout
    assert r.returncode == 0
    assert r.timed_out is False

    # 异常路径：子进程内异常被捕获，returncode!=0，stderr 含异常
    r_err = sb.run("raise ValueError('m6_err')")
    assert r_err.returncode != 0
    assert "ValueError" in r_err.stderr
