"""M5b 集成验收（设计 v0.5 §11）。

对应 §11 M5b 验收条目：主体行为学习（Actor/SampleLibrary、stat_profile、
AIInduct、MLImitate LOAO、ActorGate 复用 M3 Tester、SelfAudit）端到端集成。

所有数据确定性合成（固定 seed），mock LLM 保证独立可重跑，不依赖网络与
外部状态。仅真实 LLM 端到端用例标 network，默认 deselect。
"""
from __future__ import annotations

import datetime as _dt
import os

import numpy as np
import pandas as pd
import pytest

from quant.actor.ai_induct import AIInduct, InductResult
from quant.actor.gate import ActorGate, ActorGateResult
from quant.actor.ml_imitate import MLImitate, MLResult
from quant.actor.model import Actor, ActorKind, ActorTrade
from quant.actor.sample_lib import SampleLibrary
from quant.actor.self_audit import SelfAudit, SelfAuditResult
from quant.actor.stat_profile import StatProfile, stat_profile
from quant.mining.tester import TestConfig, Tester

# 固定 seed：所有合成数据基于此 seed 生成，保证可复现
_SEED = 2024


# ---------------------------------------------------------------------------
# 合成数据工厂（确定性）
# ---------------------------------------------------------------------------


def _buy(
    symbol: str,
    t: _dt.datetime,
    price: float,
    volume: float = 1000.0,
    sector: str = "电子",
) -> ActorTrade:
    """买入成交（sector 默认电子）。"""
    return ActorTrade(
        symbol=symbol,
        time=t,
        side="buy",
        price=price,
        volume=volume,
        context={"sector": sector},
    )


def _sell(
    symbol: str,
    t: _dt.datetime,
    price: float,
    realized_pnl: float,
    volume: float = 1000.0,
    sector: str = "电子",
) -> ActorTrade:
    """卖出成交（带 realized_pnl）。"""
    return ActorTrade(
        symbol=symbol,
        time=t,
        side="sell",
        price=price,
        volume=volume,
        realized_pnl=realized_pnl,
        context={"sector": sector},
    )


def _make_actor(
    actor_id: str,
    kind: ActorKind,
    *,
    n_paired: int = 6,
    win_rate: float = 0.6,
    seed: int = _SEED,
    sectors: tuple[str, ...] = ("电子", "医药"),
) -> Actor:
    """构造一个含 n_paired 对 buy/sell 的主体（win_rate 控制盈利占比）。

    每对：buy → 若干日后 sell，按 win_rate 决定盈亏；sector 轮转。
    日期用 timedelta 推进，避免月份溢出。
    """
    actor = Actor(id=actor_id, kind=kind)
    rng = np.random.default_rng(seed)
    base = _dt.datetime(2024, 1, 1)
    for i in range(n_paired):
        symbol = f"S{i:03d}"
        sector = sectors[i % len(sectors)]
        buy_time = base + _dt.timedelta(days=i * 10)
        sell_time = buy_time + _dt.timedelta(days=4)  # 持仓 4 天
        buy_price = float(10.0 + rng.normal(0, 0.1))
        is_win = (i / max(n_paired - 1, 1)) < win_rate
        pnl = float(rng.uniform(50.0, 150.0)) if is_win else float(-rng.uniform(30.0, 80.0))
        sell_price = buy_price + pnl / 1000.0  # 仅占位
        actor.add_trade(_buy(symbol, buy_time, buy_price, sector=sector))
        actor.add_trade(_sell(symbol, sell_time, sell_price, pnl, sector=sector))
    return actor


def _make_three_actors() -> list[Actor]:
    """构造 3 个主体：HOT_MONEY / NORTHBOUND / SELF（各自确定性 seed）。"""
    return [
        _make_actor("HM1", ActorKind.HOT_MONEY, win_rate=0.7, seed=_SEED),
        _make_actor("NB1", ActorKind.NORTHBOUND, win_rate=0.5, seed=_SEED + 1),
        _make_actor("SELF1", ActorKind.SELF, win_rate=0.6, seed=_SEED + 2),
    ]


# ---------------------------------------------------------------------------
# Mock LLM：complete_json 按序列返回候选；标 network 的用例走真实 LLM
# ---------------------------------------------------------------------------


class _MockLLM:
    """替身 LLMClient：complete_json 按计数器返回候选。

    真实 LLM 测试在 network 标记用例中走 LLMClient（无凭证 skip）。
    """

    def __init__(self, items: list[dict]):
        self._items = list(items)
        self._idx = 0
        self.model = "mock-model"

    def complete_json(self, messages: list[dict], **kw) -> dict:
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return item


def _candidate(expr: str, hyp: str = "h", rationale: str = "r") -> dict:
    return {"hypothesis": hyp, "dsl_expr": expr, "rationale": rationale}


def _feature_price_volume(trade: ActorTrade) -> np.ndarray:
    """特征向量：[price, volume]。

    PIT 约束：仅用 trade 自身可观测字段（price/volume），不含 realized_pnl
    或任何未来信息。
    """
    return np.array([trade.price, trade.volume], dtype=float)


# ---------------------------------------------------------------------------
# §11 M5b 验收 1：样本库多主体入库
# ---------------------------------------------------------------------------


def test_m5b_sample_library_multi_kind() -> None:
    """3 主体（HOT_MONEY/NORTHBOUND/SELF）入库 → by_kind 过滤正确；HOT_MONEY 默认 bias_note。"""
    actors = _make_three_actors()
    lib = SampleLibrary()
    for a in actors:
        lib.add(a)

    hm = lib.by_kind(ActorKind.HOT_MONEY)
    nb = lib.by_kind(ActorKind.NORTHBOUND)
    self_a = lib.by_kind(ActorKind.SELF)
    assert len(hm) == 1 and hm[0].id == "HM1"
    assert len(nb) == 1 and nb[0].id == "NB1"
    assert len(self_a) == 1 and self_a[0].id == "SELF1"

    # HOT_MONEY 默认带偏差声明（§4.9.2）
    decls = lib.bias_declarations()
    assert "HM1" in decls
    assert "仅上榜股样本" in decls["HM1"]
    # NORTHBOUND / SELF 默认无 bias_note → 不出现在 bias_declarations
    assert "NB1" not in decls
    assert "SELF1" not in decls


# ---------------------------------------------------------------------------
# §11 M5b 验收 2：统计画像
# ---------------------------------------------------------------------------


def test_m5b_stat_profile_computes() -> None:
    """stat_profile 算胜率/盈亏比/持仓/板块。"""
    actor = _make_actor("HM1", ActorKind.HOT_MONEY, n_paired=6, win_rate=0.6, seed=_SEED)
    profile = stat_profile(actor.trades)
    assert isinstance(profile, StatProfile)
    # 6 对 buy/sell 共 12 笔
    assert profile.n_trades == 12
    # 6 笔平仓（realized_pnl != 0），win_rate≈0.6 → 3/6~4/6
    assert 0.0 < profile.win_rate <= 1.0
    # 盈亏比有限正数（有盈有亏）
    assert profile.profit_loss_ratio > 0.0
    assert np.isfinite(profile.profit_loss_ratio)
    # 持仓：每对 buy→sell 间隔 4 天
    assert profile.avg_holding_bars == pytest.approx(4.0, abs=1e-9)
    # 板块分布含电子/医药（轮转）
    assert "电子" in profile.sector_preference
    assert "医药" in profile.sector_preference


# ---------------------------------------------------------------------------
# §11 M5b 验收 3：AI 归纳候选
# ---------------------------------------------------------------------------


def test_m5b_ai_induct_candidates() -> None:
    """mock LLM 返回合法 DSL → AIInduct 产 candidates（network 标记真实）。"""
    actor = _make_actor("HM1", ActorKind.HOT_MONEY, n_paired=4, win_rate=0.7, seed=_SEED)
    llm = _MockLLM(
        [
            _candidate("rank(ts_delta(close,5))"),
            _candidate("ts_mean(volume,10)"),
        ]
    )
    inductor = AIInduct(llm)
    res = inductor.induct(actor, budget=2)
    assert isinstance(res, InductResult)
    assert res.n_samples == 2
    assert len(res.candidates) == 2
    exprs = {c["dsl_expr"] for c in res.candidates}
    assert "rank(ts_delta(close,5))" in exprs
    assert "ts_mean(volume,10)" in exprs
    for c in res.candidates:
        assert "hypothesis" in c and "rationale" in c


@pytest.mark.network
def test_m5b_ai_induct_real_llm_network() -> None:
    """真实 LLM 端到端（network）：无凭证 skip。"""
    from quant.llm.client import LLMClient, _load_env

    _load_env()
    if not (
        os.environ.get("LLM_BASE_URL")
        and os.environ.get("LLM_API_KEY")
        and os.environ.get("LLM_MODEL")
    ):
        pytest.skip("LLM 凭证未配置，跳过真实 API 测试")
    actor = _make_actor("HM1", ActorKind.HOT_MONEY, n_paired=4, win_rate=0.7, seed=_SEED)
    inductor = AIInduct(LLMClient())
    res = inductor.induct(actor, budget=1)
    assert isinstance(res, InductResult)
    assert res.n_samples == 1


# ---------------------------------------------------------------------------
# §11 M5b 验收 4：ML LOAO OOS
# ---------------------------------------------------------------------------


def test_m5b_ml_loao_oos() -> None:
    """MLImitate.fit_loao（≥3 actor）→ held_out_actors 含全部；oos_ic 是 float。"""
    # 构造 3 个 actor，PnL 与 price 强线性相关（slope=2.0）→ LOAO 可学
    rng = np.random.default_rng(_SEED)
    base = _dt.datetime(2024, 1, 1)
    actors: list[Actor] = []
    for a in range(3):
        actor = Actor(id=f"A{a}", kind=ActorKind.HOT_MONEY)
        bias = float(a - 1)
        for i in range(8):
            price = 10.0 + i + 0.1 * a
            volume = 1000.0 * (1 + a)
            pnl = 2.0 * price + bias + float(rng.normal(0, 0.01))
            actor.add_trade(
                ActorTrade(
                    symbol=f"S{i:03d}",
                    time=base.replace(day=i + 1),
                    side="buy",
                    price=price,
                    volume=volume,
                    realized_pnl=pnl,
                    context={"sector": "电子"},
                )
            )
        actors.append(actor)

    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    assert isinstance(res, MLResult)
    # held_out_actors 含全部 actor id（每折留出 1 个）
    assert set(res.held_out_actors) == {a.id for a in actors}
    assert len(res.held_out_actors) == len(actors)
    # oos_ic 是 float，落在 [-1, 1]
    assert isinstance(res.oos_ic, float)
    assert -1.0 <= res.oos_ic <= 1.0
    # coefs 维度 = 特征维度
    assert res.coefs.shape == (2,)
    # 强信号 → oos_ic > 0
    assert res.oos_ic > 0.0, f"强信号下 oos_ic 应 > 0，实际 {res.oos_ic}"


# ---------------------------------------------------------------------------
# §11 M5b 验收 5：标准门禁复用 M3 Tester
# ---------------------------------------------------------------------------


# 合成长格式 panel 辅助（与 test_actor_gate 同构，保证强弱候选可复现）
_PANEL_RNG = np.random.default_rng(7)
_PANEL_SYMBOLS = [f"S{i:03d}" for i in range(100)]
_PANEL_N_DATES = 20
_PANEL_DATES = (
    pd.date_range("2024-01-01", periods=_PANEL_N_DATES, freq="D").astype("int64") // 10**9
)


def _panel_from(values_fn, n_dates: int = _PANEL_N_DATES) -> pd.DataFrame:
    """生成长格式 panel：列 trade_date / symbol / value。"""
    rows = []
    for i in range(n_dates):
        vals = values_fn(i)
        for s, v in zip(_PANEL_SYMBOLS, vals):
            rows.append((_PANEL_DATES[i], s, float(v)))
    return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])


def _strong_factor_panel() -> pd.DataFrame:
    """因子截面单调 + 小噪声，IC 高、IR 可解。"""

    def fn(i: int) -> np.ndarray:
        base = np.arange(len(_PANEL_SYMBOLS), dtype=float)
        return base + _PANEL_RNG.normal(0, 0.5, size=len(_PANEL_SYMBOLS))

    return _panel_from(fn)


def _returns_panel_aligned(factor_panel: pd.DataFrame, slope: float = 0.001) -> pd.DataFrame:
    """收益与因子同序：returns = slope*rank(factor) + 噪声。"""

    def fn(i: int) -> np.ndarray:
        f_vals = factor_panel[factor_panel["trade_date"] == _PANEL_DATES[i]]["value"].to_numpy()
        order = np.argsort(f_vals)
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(len(order), dtype=float)
        return slope * ranked + _PANEL_RNG.normal(0, slope * 0.3, size=len(order))

    return _panel_from(fn)


def _random_panel(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _panel_from(lambda i: rng.normal(0, 0.01, size=len(_PANEL_SYMBOLS)))


def _make_tester() -> Tester:
    """复用 M3 Tester，阈值放低 min_long_short_annual 以便强候选稳过。"""
    return Tester(TestConfig(min_long_short_annual=0.0))


def test_m5b_standard_gate_reuses_m3() -> None:
    """强候选 → M3 Tester 通过 → passed=True；一致性 path_supports 不提升通过率。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())

    # 强候选（无 path_supports）→ passed=True
    res_no_support = gate.test(factor, returns, p_value=0.001, hypothesis_budget=10)
    assert isinstance(res_no_support, ActorGateResult)
    assert res_no_support.passed is True, f"reasons={res_no_support.test_result.reasons}"

    # 强候选 + 全路支持 → passed=True，一致性 = 1.0 但不门控（不变成"更通过"）
    res_full_support = gate.test(
        factor, returns, p_value=0.001, hypothesis_budget=10,
        path_supports=[True, True, True],
    )
    assert res_full_support.passed is True
    assert res_full_support.method_consistency == 1.0
    # 一致性非门控：passed 仅由 Tester 定
    assert res_full_support.consistency_as_evidence_only is True


# ---------------------------------------------------------------------------
# §11 M5b 验收 6：一致性仅为证据（非门控，§4.9.4）
# ---------------------------------------------------------------------------


def test_m5b_consistency_evidence_only() -> None:
    """三路全支持 + 弱候选 → passed=False（一致性非门控，§4.9.4）。"""
    factor = _random_panel(seed=3)
    returns = _random_panel(seed=4)
    gate = ActorGate(_make_tester())
    res = gate.test(
        factor, returns, p_value=0.5, hypothesis_budget=10,
        path_supports=[True, True, True],
    )
    # 一致性满分但候选弱 → 不入库
    assert res.method_consistency == 1.0
    assert res.passed is False
    assert res.consistency_as_evidence_only is True
    # 人审始终必须
    assert res.human_review_required is True
    # reasons 含 M3 Tester 拒因
    assert len(res.reasons) >= 1


# ---------------------------------------------------------------------------
# §11 M5b 验收 7：自身画像降级（SelfAudit）
# ---------------------------------------------------------------------------


def test_m5b_self_audit_degraded() -> None:
    """SelfAudit 自身小样本 → small_sample=True + 规则提醒（追高/割肉等）。"""
    base = _dt.datetime(2024, 1, 5)
    # 追高：买 9.80 接近当日高 10.00（距 2% < 5%）
    buy = _buy("600519", base.replace(hour=14, minute=30), 9.80)
    # 割肉 + 持仓过久：sell 在 80 天后，成本 10.00 卖 9.00（亏 10% < -8%）
    sell = _sell(
        "600519",
        base + _dt.timedelta(days=80),
        9.00,
        realized_pnl=-100.0,
    )
    day_highs = {("600519", base.date()): 10.00}
    trades = [buy, sell]

    res = SelfAudit(
        chase_threshold=0.05,
        loss_cut_threshold=-0.08,
        holding_days_too_long=60,
        small_sample_threshold=30,
    ).audit(trades, day_highs=day_highs)

    assert isinstance(res, SelfAuditResult)
    # 自身小样本降级
    assert res.small_sample is True
    assert res.n_trades == len(trades)
    # 至少触发追高/割肉/持仓过久之一
    kinds = {r.kind for r in res.reminders}
    assert kinds & {"chasing_high", "cutting_loss", "holding_too_long"}, (
        f"应触发至少一种规则提醒，实际 kinds={kinds}"
    )


# ---------------------------------------------------------------------------
# §11 M5b 验收 8：三路产出可入 ActorGate（端到端集成）
# ---------------------------------------------------------------------------


def test_m5b_three_paths_produce_candidates() -> None:
    """端到端：3 actor → stat_profile 画像 + AIInduct(mock) 候选 + MLImitate coefs，
    三路产出可入 ActorGate。端到端不崩。"""
    actors = _make_three_actors()

    # 路径1：stat_profile 逐主体画像
    profiles = {a.id: stat_profile(a.trades) for a in actors}
    for a in actors:
        p = profiles[a.id]
        assert isinstance(p, StatProfile)
        assert p.n_trades > 0
        assert 0.0 <= p.win_rate <= 1.0
        assert p.profit_loss_ratio >= 0.0  # 可能为 inf（全胜），不崩即可

    # 路径2：AIInduct（mock LLM）逐主体候选
    llm = _MockLLM(
        [
            _candidate("rank(ts_delta(close,5))"),
            _candidate("ts_mean(volume,10)"),
            _candidate("rank(ts_rank(volume,20))"),
        ]
    )
    inductor = AIInduct(llm)
    induct_results = {a.id: inductor.induct(a, budget=1) for a in actors}
    for a in actors:
        r = induct_results[a.id]
        assert isinstance(r, InductResult)
        assert r.n_samples == 1
        # mock 返回合法 DSL → candidates 非空
        assert len(r.candidates) >= 1

    # 路径3：MLImitate LOAO 聚合 coefs
    ml = MLImitate()
    ml_res = ml.fit_loao(actors, _feature_price_volume)
    assert isinstance(ml_res, MLResult)
    assert set(ml_res.held_out_actors) == {a.id for a in actors}
    assert ml_res.coefs.shape == (2,)
    assert isinstance(ml_res.oos_ic, float)

    # 三路产出汇总：构造候选因子 panel + path_supports，入 ActorGate
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    gate = ActorGate(_make_tester())

    # path_supports：三路是否支持（此处全 True，作为一致性证据）
    stat_supports = all(profiles[a.id].win_rate > 0.0 for a in actors)
    ai_supports = all(len(induct_results[a.id].candidates) > 0 for a in actors)
    ml_supports = ml_res.oos_ic > -1.0  # 有方向性信息即支持
    path_supports = [stat_supports, ai_supports, ml_supports]

    res = gate.test(
        factor, returns,
        p_value=0.001, hypothesis_budget=10,
        path_supports=path_supports,
    )
    assert isinstance(res, ActorGateResult)
    # 强候选 → passed（一致性仅为证据）
    assert res.passed is True
    assert res.human_review_required is True
    # method_consistency = sum(path_supports)/3
    expected_consistency = sum(1 for s in path_supports if s) / 3.0
    assert abs(res.method_consistency - expected_consistency) < 1e-9
