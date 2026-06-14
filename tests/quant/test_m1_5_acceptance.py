"""M1.5 集成验收测试（设计 v0.5 §11 M1.5 验收 6 条，capstone）。

端到端串起 M1.5：StrategyRunner（多策略隔离+冲突裁决）→ PortfolioOptimizer
（cvxpy QP + 多 lot 整数化 + gap）→ RebalancePolicy/stop_loss_signals →
StrategyLifecycle（8 态状态机）。合成数据驱动，确定性可重跑。
对应设计 §11 的 6 条 M1.5 验收条目，每条至少一个测试函数。
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from quant.backtest.engine import Position
from quant.backtest.sim_broker import BarSnapshot, Order, SimBroker
from quant.clock import BacktestClock
from quant.factor.context import FactorContext
from quant.factor.factors.momentum import MomentumFactor
from quant.factor.registry import FactorRegistry
from quant.strategy.context import BarContext
from quant.strategy.lifecycle import StrategyLifecycle, StrategyStatus
from quant.strategy.optimizer import OptimizerConfig, PortfolioOptimizer
from quant.strategy.rebalance import RebalancePolicy
from quant.strategy.runner import StrategyRunner
from quant.strategy.signal import Signal

# 固定 RNG seed，保证合成数据确定性
_SEED = 42


# ===========================================================================
# 验收 1：多策略并行回测（隔离）
# ===========================================================================
def _make_bar_ctx(symbol: str = "600519") -> BarContext:
    """构造最小可用 BarContext（空因子面板、空持仓）。"""
    bar = BarSnapshot(
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=10000.0, limit_up=110.0, limit_down=90.0,
    )
    return BarContext(
        bar=bar,
        symbol=symbol,
        decision_time=_dt.datetime(2024, 1, 2, 16, 0),
        clock=BacktestClock(_dt.datetime(2024, 1, 2, 16, 0)),
        account_id="acct1",
        positions={},
        factor_panel=pd.DataFrame(),
        rules={},
        trace_id="trace-m15",
    )


class _HealthyStrategy:
    """正常策略：产出两条 Signal。"""

    name = "healthy"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        return [
            Signal(symbol="600519", direction=1, strength=0.5, target_weight=0.3),
            Signal(symbol="000001", direction=1, strength=0.4, target_weight=0.2),
        ]

    def on_fill(self, ctx: Any) -> None:
        pass


class _CrashStrategy:
    """异常策略：on_bar 抛 RuntimeError。"""

    name = "crash"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        raise RuntimeError("strategy on_bar boom")

    def on_fill(self, ctx: Any) -> None:
        pass


def test_m15_multi_strategy_isolation() -> None:
    """§11 验收 1：多策略并行调度，单策略异常隔离不阻断整 bar。

    - 正常策略产出的 Signal 完整返回
    - 异常策略被隔离，不影响其他策略
    - run 不抛
    """
    runner = StrategyRunner()
    runner.register(_HealthyStrategy())
    runner.register(_CrashStrategy())
    ctx = _make_bar_ctx()

    signals = runner.run(ctx)  # 不抛：异常被隔离

    # 正常策略的两条 Signal 完整返回
    assert len(signals) == 2
    syms = {s.symbol for s in signals}
    assert syms == {"600519", "000001"}


# ===========================================================================
# 验收 2：优化约束满足
# ===========================================================================
def test_m15_optimizer_constraints() -> None:
    """§11 验收 2：PortfolioOptimizer 连续解满足满仓、单票上限、换手上限。

    合成 4 symbol 多头信号，max_single=0.5（n*max_single>=1 可行），
    提供 current_weights 使换手硬上限生效。
    """
    config = OptimizerConfig(max_single=0.50, max_turnover=0.80)
    opt = PortfolioOptimizer(config)
    signals = [
        Signal(symbol=s, direction=1, strength=a)
        for s, a in [("600519", 0.9), ("000858", 0.6), ("002304", 0.4), ("600009", 0.2)]
    ]
    # 起始等权 current，换手上限宽松确保可行
    current = {s: 0.25 for s in ["600519", "000858", "002304", "600009"]}

    result = opt.optimize(signals, current_weights=current)
    w = result.continuous_weights

    # 满仓约束：sum(w) ≈ 1
    assert abs(sum(w.values()) - 1.0) < 1e-3
    # 单票上限：每项 <= max_single
    for v in w.values():
        assert v <= config.max_single + 1e-4
    # 换手硬上限：|w - current|_1 <= max_turnover（+容差）
    turnover = sum(abs(w.get(s, 0.0) - current.get(s, 0.0)) for s in set(w) | set(current))
    assert turnover <= config.max_turnover + 1e-3


# ===========================================================================
# 验收 3：QP-vs-整数化 gap < 阈值
# ===========================================================================
def test_m15_gap_within_threshold() -> None:
    """§11 验收 3：连续 QP 解与整数化解的目标函数 gap 在阈值内。

    合成 4 symbol α，整数化粒度细（ref_price=1 → n_lots 大），
    gap 应远小于宽松阈值 0.1。默认 gap_threshold=0.02 时不应触发告警。
    """
    config = OptimizerConfig(max_single=0.50, gap_threshold=0.02)
    opt = PortfolioOptimizer(config)
    signals = [
        Signal(symbol=s, direction=1, strength=a)
        for s, a in [("600519", 0.9), ("000858", 0.5), ("002304", 0.3), ("600009", 0.1)]
    ]

    result = opt.optimize(signals)

    # gap 非负且在宽松阈值内（合成数据 lot 粒度细）
    assert result.gap >= 0.0
    assert result.gap < 0.1
    # 整数化损失小：默认 gap_threshold 下不应告警
    assert result.gap_warning is False, f"gap_warning 触发：gap={result.gap}（极端配置或整数化粒度不足）"


# ===========================================================================
# 验收 4：换手 ≤ 上限
# ===========================================================================
def test_m15_turnover_within_limit() -> None:
    """§11 验收 4：整数化后权重相对 current 的 L1 换手 <= max_turnover。

    提供 current_weights（等权），optimize 后断言换手受硬上限约束。
    max_turnover 设为足够使 QP 可行的值（current 等权 0.25，目标偏移不大）。
    """
    symbols = ["600519", "000858", "002304", "600009"]
    config = OptimizerConfig(max_single=0.50, max_turnover=0.40)
    opt = PortfolioOptimizer(config)
    signals = [
        Signal(symbol=s, direction=1, strength=a)
        for s, a in [("600519", 0.8), ("000858", 0.5), ("002304", 0.4), ("600009", 0.3)]
    ]
    current = {s: 0.25 for s in symbols}

    result = opt.optimize(signals, current_weights=current)
    w_int = result.weights

    # L1 换手 <= max_turnover + 容差（整数化可能引入微小越界）
    turnover = sum(abs(w_int.get(s, 0.0) - current.get(s, 0.0)) for s in symbols)
    assert turnover <= config.max_turnover + 0.05


# ===========================================================================
# 验收 5：生命周期状态机可迁移
# ===========================================================================
def test_m15_lifecycle_full_path() -> None:
    """§11 验收 5：StrategyLifecycle 全路径迁移成功 + 非法迁移抛 ValueError。

    路径：draft→backtested→paper→approved（门禁 ic>=0.03）→
          live→monitoring→degraded→offline。
    门禁用 metrics{ic:0.05} 通过；非法迁移（如 draft→live）抛 ValueError。
    """
    lc = StrategyLifecycle(strategy="momentum_top2")
    assert lc.status is StrategyStatus.DRAFT

    # 全路径合法迁移
    lc.transition(StrategyStatus.BACKTESTED)
    lc.transition(StrategyStatus.PAPER)
    # 门禁：ic=0.05 >= 0.03 通过
    lc.metrics = {"ic": 0.05}
    lc.transition(StrategyStatus.APPROVED)
    assert lc.approved is True
    lc.transition(StrategyStatus.LIVE)
    lc.transition(StrategyStatus.MONITORING)
    lc.transition(StrategyStatus.DEGRADED)
    lc.transition(StrategyStatus.OFFLINE)
    assert lc.status is StrategyStatus.OFFLINE  # 终态


def test_m15_lifecycle_illegal_transition_raises() -> None:
    """§11 验收 5（补充）：非法迁移（跨态跳跃）抛 ValueError。"""
    lc = StrategyLifecycle(strategy="bad")
    # DRAFT 只能去 BACKTESTED，跳到 LIVE 非法
    with pytest.raises(ValueError):
        lc.transition(StrategyStatus.LIVE)


def test_m15_lifecycle_gate_blocks_low_ic() -> None:
    """§11 验收 5（补充）：门禁 ic<0.03 时 APPROVED 迁移被拒。"""
    lc = StrategyLifecycle(strategy="weak")
    lc.transition(StrategyStatus.BACKTESTED)
    lc.metrics = {"ic": 0.01}  # 不达标
    with pytest.raises(ValueError):
        lc.transition(StrategyStatus.APPROVED)


# ===========================================================================
# 验收 6：集成回测（StrategyRunner + Optimizer + RebalancePolicy + SimBroker）
# ===========================================================================
class _MomentumTop2Strategy:
    """简单动量策略：用 factor_panel 的 momentum_20 选 top-2 产 Signal。

    required_factors 声明 momentum_20；on_bar 据面板排序取前二，
    产出多头 Signal（strength 取动量值，作为优化器 alpha）。
    """

    name = "momentum_top2"
    required_factors = ["momentum_20"]

    def __init__(self) -> None:
        self._top_n = 2

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        panel = ctx.factor_panel
        if panel.empty or "momentum_20" not in panel.columns:
            return []
        mom = panel["momentum_20"].dropna()
        if mom.empty:
            return []
        tops = mom.sort_values(ascending=False).head(self._top_n).index.tolist()
        return [
            Signal(symbol=sym, direction=1, strength=float(mom.loc[sym]))
            for sym in tops
        ]

    def on_fill(self, ctx: Any) -> None:
        pass


# 沪市主板规则（与 test_m1_acceptance 一致，便于 SimBroker 撮合）
_RULE_MAIN = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
    "min_buy": 100,
    "lot_increment": 100,
    "fees": {
        "stamp": {"value": 0.0005, "_confidence": "provisional"},
        "transfer": {"value": 0.00001, "_confidence": "provisional"},
        "commission": {"value": None, "_confidence": "provisional"},
        "exchange": {"value": None, "_confidence": "provisional"},
    },
}


def _synth_market(n_symbols: int, n_days: int, seed: int):
    """合成 N symbol × T day panel：close 带趋势+噪声，固定 seed。

    available_at = trade_date 当日 16:00（PIT 安全）。bars 用当日 close 简化。
    """
    rng = np.random.default_rng(seed)
    start = _dt.date(2021, 1, 4)
    days = [_start_to_date(start, i) for i in range(n_days)]
    symbols = [f"60000{i}.SH" for i in range(n_symbols)]

    rows = []
    bars: dict = {}
    for j, sym in enumerate(symbols):
        price = 20.0 + j * 5.0
        drift = rng.uniform(0.0, 0.003)  # 轻微上涨，动量信号明确
        noise = rng.normal(0, 0.01, size=n_days)
        prices = price * np.cumprod(1 + drift + noise)
        for i, d in enumerate(days):
            c = round(float(prices[i]), 2)
            rows.append({
                "symbol": sym, "trade_date": d,
                "available_at": _day_end(d), "close": c,
            })
            bars[(sym, d)] = BarSnapshot(
                open=c, high=c * 1.02, low=c * 0.98, close=c,
                volume=1_000_000.0,
                limit_up=c * 1.10, limit_down=c * 0.90,
            )
    return pd.DataFrame(rows), bars, days


def _start_to_date(start: _dt.date, i: int) -> _dt.date:
    """start + i 个工作日（跳过周末）。"""
    d = start
    stepped = 0
    while stepped < i:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            stepped += 1
    return d


def _day_end(d: _dt.date) -> _dt.datetime:
    """trade_date 当日 16:00（收盘后决策时刻）。"""
    return _dt.datetime.combine(d, _dt.time(hour=16, minute=0))


def test_m15_integrated_backtest() -> None:
    """§11 验收 6：StrategyRunner→Optimizer→RebalancePolicy→SimBroker 串联跑通。

    简化集成（不必接完整 BacktestEngine.run）：
    - 合成 4 symbol × 30 日 panel
    - 每个 bar：FactorRegistry 算 momentum_20 → StrategyRunner 选 top-2 产 Signal
      → PortfolioOptimizer 产目标权重 → RebalancePolicy 判定是否再平衡
      → 首日触发时手动构造 SimBroker 买单撮合验证串联
    断言：跑通无异常、产出 fills、equity 非全 NaN。
    """
    panel, bars, days = _synth_market(n_symbols=4, n_days=30, seed=_SEED)
    symbols = sorted(panel["symbol"].unique().tolist())

    # 因子注册表
    registry = FactorRegistry()
    registry.register(MomentumFactor(window=20))

    # 策略 + 调度器 + 优化器
    runner = StrategyRunner()
    runner.register(_MomentumTop2Strategy())
    optimizer = PortfolioOptimizer(OptimizerConfig(max_single=0.60, max_turnover=1.0))
    broker = SimBroker()

    cash = 1_000_000.0
    positions: dict[str, Position] = {}
    fills: list = []
    equity_curve: list = []
    rebalance_policy = RebalancePolicy(frequency="daily")
    ordered = False

    for day in days:
        # 1. PIT 安全装配 factor_panel
        decision_time = _day_end(day)
        factor_panel = registry.compute_panel(
            names=["momentum_20"],
            t=decision_time,
            universe=symbols,
            snapshot_id="snap_m15_integrated",
            panel=panel,
        )

        # 2. 装配 BarContext（取首个 symbol 的 bar 作为占位）
        any_bar = bars.get((symbols[0], day))
        ctx = BarContext(
            bar=any_bar,
            symbol=symbols[0],
            decision_time=decision_time,
            clock=BacktestClock(decision_time),
            account_id="acct_integrated",
            positions=dict(positions),
            factor_panel=factor_panel,
            rules=_RULE_MAIN,
            trace_id="trace_integrated",
        )

        # 3. StrategyRunner 选 top-2 产 Signal
        signals = runner.run(ctx)

        # 4. 当前权重（按 close mark-to-market）
        bars_today = {s: bars.get((s, day)) for s in symbols}
        current_weights = _current_weights(positions, bars_today, cash)

        # 5. RebalancePolicy 判定是否再平衡
        if signals and rebalance_policy.should_rebalance(today=day):
            # 6. PortfolioOptimizer 产目标权重
            result = optimizer.optimize(
                signals,
                current_weights=current_weights or None,
                total_capital=cash + _positions_market_value(positions, bars_today),
            )
            target_weights = result.weights

            # 7. 首日：据目标权重差分构造买单，SimBroker 撮合验证串联
            if not ordered and target_weights:
                total_value = cash + _positions_market_value(positions, bars_today)
                for sym, tw in target_weights.items():
                    bar = bars.get((sym, day))
                    if bar is None:
                        continue
                    price = bar.close
                    target_value = tw * total_value
                    current_value = positions.get(sym, Position()).qty * price
                    delta_value = target_value - current_value
                    if delta_value <= 0:
                        continue
                    # 整百股下单（A 股 lot=100）
                    qty = int(delta_value / price // 100) * 100
                    if qty < _RULE_MAIN["min_buy"]:
                        continue
                    order = Order(symbol=sym, side="buy", qty=qty, order_type="market")
                    res = broker.match(
                        order, bar, _RULE_MAIN,
                        position_qty=positions.get(sym, Position()).qty,
                    )
                    if res.filled:
                        _apply_fill_to_positions(positions=positions,
                                                 order=order, res=res)
                        cash -= res.cost.fill_price * res.fill_qty + (
                            res.cost.commission + res.cost.stamp + res.cost.transfer
                        )
                    fills.append({
                        "date": day, "symbol": sym, "side": "buy",
                        "qty": qty, "filled": res.filled,
                        "fill_qty": res.fill_qty, "fill_price": res.fill_price,
                    })
                ordered = True

        # 8. 当日权益 mark-to-market
        mkt = _positions_market_value(positions, bars_today)
        equity_curve.append(cash + mkt)

    # 断言：跑通无异常（到这里即通过）
    # 产出 fills：首日应至少有一笔成交
    assert len(fills) >= 1, "集成回测未产出任何 fills"
    assert any(f["filled"] for f in fills), "无成交 fill"

    # 权益非全 NaN
    eq = pd.Series(equity_curve, index=days, name="equity")
    assert not eq.isna().any(), "权益曲线含 NaN"
    assert (eq > 0).all(), "权益出现非正值"


# ---------------------------------------------------------------------------
# 集成回测辅助函数
# ---------------------------------------------------------------------------
def _positions_market_value(
    positions: dict[str, Position], bars_today: dict
) -> float:
    """持仓按当日 close 的市值。"""
    total = 0.0
    for sym, pos in positions.items():
        if pos.qty == 0:
            continue
        bar = bars_today.get(sym)
        if bar is None:
            continue
        total += pos.qty * bar.close
    return total


def _current_weights(
    positions: dict[str, Position], bars_today: dict, cash: float
) -> dict[str, float]:
    """当前持仓权重（按市值归一）。"""
    total = cash + _positions_market_value(positions, bars_today)
    if total <= 0:
        return {}
    weights = {}
    for sym, pos in positions.items():
        if pos.qty == 0:
            continue
        bar = bars_today.get(sym)
        if bar is None:
            continue
        weights[sym] = pos.qty * bar.close / total
    return weights


def _apply_fill_to_positions(
    positions: dict[str, Position], order: Order, res: Any
) -> None:
    """成交回写持仓（加权平均成本），现金由调用方在外层扣减。"""
    assert res.cost is not None
    fill_price = res.cost.fill_price
    qty = res.fill_qty
    pos = positions.setdefault(order.symbol, Position())
    new_qty = pos.qty + qty
    if new_qty > 0:
        pos.avg_cost = (pos.avg_cost * pos.qty + fill_price * qty) / new_qty
    pos.qty = new_qty


# ---------------------------------------------------------------------------
# pytest 已在顶部导入（pytest.raises 供生命周期测试使用）
# ---------------------------------------------------------------------------
