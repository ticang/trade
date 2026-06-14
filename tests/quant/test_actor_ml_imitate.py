"""主体行为学习 Task 4 测试：ML 模仿（设计 v0.5 §4.9.3 路径3）。

Leave-One-Actor-Out：每次留出 1 个 actor 全期作 OOS，其余 actor 训练。
- 标签 = trade.realized_pnl（连续值，非"是否盈利"二元）
- 特征由 feature_fn 给出（PIT 约束由调用方保证）
- 训练：线性回归（np.linalg.lstsq）逐 LOAO 折
- OOS IC：留出 actor 预测 PnL vs 实际 PnL 的 rank IC，多折聚合

覆盖点：
- fit_loao 返回 MLResult，coefs 非空
- 标签为连续 realized_pnl（特征与 PnL 线性相关时 coefs 方向对）
- held_out_actors 含全部 actor id（每 actor 被留出一次）
- oos_ic ∈ [-1,1]，强信号时 > 0
- predict = features @ coefs + intercept
- feature_fn PIT 约束由调用方保证（docstring/注释明示）

TDD：本文件先于 quant/actor/ml_imitate.py 实现，import 失败为预期红线。
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from quant.actor.model import Actor, ActorKind, ActorTrade
from quant.actor.ml_imitate import MLImitate, MLResult


# ---------------------------------------------------------------------------
# 合成数据：多 actor，每 actor 多 trades，特征 = [price, volume]
# PIT 约束由本测试 feature_fn 体现（仅用 trade 自身字段，不窥后视）
# ---------------------------------------------------------------------------
def _feature_price_volume(trade: ActorTrade) -> np.ndarray:
    """特征向量：[price, volume]。

    PIT 约束：仅用 trade 自身可观测字段（price/volume），不含 realized_pnl
    或任何未来信息。真实使用时由调用方在 feature_fn 中保证 PIT。
    """
    return np.array([trade.price, trade.volume], dtype=float)


def _make_actors(
    n_actors: int = 3,
    n_trades_per_actor: int = 6,
    *,
    signal_slope: float = 2.0,
) -> list[Actor]:
    """构造 n_actors 个主体，每 actor 含 n_trades 笔 trades。

    PnL 与 price 线性相关：realized_pnl = signal_slope * price + 噪声。
    noise 与 actor id 绑定（不同 actor 不可交换特征→LOAO 才有意义）。
    """
    actors: list[Actor] = []
    rng = np.random.default_rng(42)
    base = datetime(2024, 1, 1)
    for a in range(n_actors):
        actor = Actor(id=f"A{a}", kind=ActorKind.HOT_MONEY)
        # 每 actor 自带偏置（不可由特征完全解释，留出时仍可学）
        actor_bias = float(a - n_actors // 2)
        for i in range(n_trades_per_actor):
            price = 10.0 + i + 0.1 * a
            volume = 1000.0 * (1 + a)
            pnl = signal_slope * price + actor_bias + float(rng.normal(0, 0.01))
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
    return actors


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_fit_returns_result():
    """fit_loao 返回 MLResult，coefs 非空（维度 = 特征维度）。"""
    actors = _make_actors(n_actors=3, n_trades_per_actor=6)
    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    assert isinstance(res, MLResult)
    assert res.coefs is not None
    assert res.coefs.shape == (2,)  # [price, volume]
    assert np.all(np.isfinite(res.coefs))
    assert np.isfinite(res.intercept)


def test_label_is_pnl_not_binary():
    """标签为连续 realized_pnl：特征与 PnL 线性相关时，coefs 方向对。

    构造 pnl = signal_slope * price + ...，强信号 slope=2.0 时 price 系数
    应为正（若误用二元 0/1 标签，线性回归系数会被压缩/扭曲）。
    """
    actors = _make_actors(n_actors=3, n_trades_per_actor=8, signal_slope=2.0)
    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    # price 是第一维特征；强正信号下其系数应显著为正
    assert res.coefs[0] > 0.5, f"price 系数应正且显著，实际 {res.coefs[0]}"
    # 验证标签连续性：训练矩阵 Y 应含连续值范围（间接由 fit 成功反推）


def test_loao_holds_out_each_actor():
    """held_out_actors 含全部 actor id（每 actor 被留出恰好一次）。"""
    actors = _make_actors(n_actors=4, n_trades_per_actor=5)
    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    expected_ids = {a.id for a in actors}
    assert set(res.held_out_actors) == expected_ids
    # 每 actor 被留出恰好一次（无重复）
    assert len(res.held_out_actors) == len(actors)


def test_oos_ic_computed():
    """oos_ic ∈ [-1, 1]；强信号时 > 0。"""
    actors = _make_actors(n_actors=3, n_trades_per_actor=10, signal_slope=3.0)
    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    assert isinstance(res.oos_ic, float)
    assert -1.0 <= res.oos_ic <= 1.0
    # 强信号（pnl = 3 * price + 偏置）→ LOAO OOS 应正向
    assert res.oos_ic > 0.0, f"强信号下 oos_ic 应 > 0，实际 {res.oos_ic}"


def test_oos_ic_zero_signal_near_zero():
    """信号随机化（pnl 与特征无关）→ oos_ic 应接近 0（无方向性）。"""
    # 构造与特征完全无关的随机 pnl
    rng = np.random.default_rng(0)
    actors: list[Actor] = []
    base = datetime(2024, 1, 1)
    for a in range(3):
        actor = Actor(id=f"R{a}", kind=ActorKind.HOT_MONEY)
        for i in range(15):
            actor.add_trade(
                ActorTrade(
                    symbol=f"S{i:03d}",
                    time=base.replace(day=i + 1),
                    side="buy",
                    price=10.0 + i,
                    volume=1000.0,
                    realized_pnl=float(rng.normal(0, 1)),
                )
            )
        actors.append(actor)
    ml = MLImitate()
    res = ml.fit_loao(actors, _feature_price_volume)
    # 无信号 → |oos_ic| 不应远超 0（允许噪声，但 < 0.5 宽松阈值）
    assert abs(res.oos_ic) < 0.5, f"无信号下 oos_ic 应近 0，实际 {res.oos_ic}"


def test_predict_linear():
    """predict(coefs, intercept, features) = features @ coefs + intercept。"""
    ml = MLImitate()
    coefs = np.array([1.5, -0.5])
    intercept = 0.3
    features = np.array(
        [
            [1.0, 2.0],
            [3.0, 4.0],
            [5.0, 6.0],
        ]
    )
    pred = ml.predict(coefs, intercept, features)
    expected = features @ coefs + intercept
    assert pred.shape == (3,)
    np.testing.assert_allclose(pred, expected)


def test_pit_note():
    """feature_fn PIT 约束在文档中明示（docstring/注释提及 PIT）。

    防前视：realized_pnl 不得作为特征。本测试验证模块说明包含 PIT 约束。
    """
    import quant.actor.ml_imitate as mod

    src = mod.__doc__ or ""
    assert "PIT" in src or "point-in-time" in src.lower(), (
        "ml_imitate 模块 docstring 必须明示 PIT 约束由调用方保证"
    )
