"""M1 集成验收测试（设计 v0.5 §11 M1 验收 6 条，capstone）。

端到端串起：rule_loader → TradingRuleProvider.rules_for → SimBroker.match →
FactorContext(PIT) → BacktestEngine.run。合成数据驱动，确定性可重跑。
对应设计 §11 的 6 条 M1 验收条目，每条至少一个测试函数。
"""
from __future__ import annotations

import datetime as _dt
import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from quant.backtest.engine import (
    BacktestEngine,
    BacktestStrategy,
)
from quant.backtest.sim_broker import BarSnapshot, Order, SimBroker
from quant.data.sqlite_store import SqliteStore
from quant.factor.context import FactorContext, LookAheadError
from quant.factor.factors.momentum import MomentumFactor
from quant.factor.registry import FactorRegistry
from quant.providers.rule_loader import load_rules
from quant.providers.trading_rule import TradingRuleProvider

# 固定 RNG seed，保证合成数据确定性
_SEED = 42


# ---------------------------------------------------------------------------
# 规则 fixture（沪市主板）：测试用固定 RULE_JSON，与 rules_v1.yaml sse_main 一致
# ---------------------------------------------------------------------------
RULE_MAIN = {
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

def _day_end(d: _dt.date) -> _dt.datetime:
    """trade_date 当日 16:00（收盘后决策时刻）。"""
    return _dt.datetime.combine(d, _dt.time(hour=16, minute=0))


# ===========================================================================
# 验收 1：规则 fixture 100% 加载并经撮合器验证
# ===========================================================================
@pytest.fixture
def store(tmp_db):
    """起停 SqliteStore，加载 M0.5 种子。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)
    yield s
    s.stop()


def test_m1_rule_fixtures_load_and_apply(store):
    """§11 验收 1：load_rules 加载当前主板规则，golden 事实经 SimBroker 验证。

    - 600519（沪市主板）命中 sse_main_stock：±10%、T+1、min_buy 100、lot 100
    - 688981（科创板）当前延期，不命中规则
    - 撮合尊重规则：主板非 100 股整数倍买单 → illegal_lot 被拒
    - 沪市主板买单 100（满足 min_buy）+ 正常 bar → 成交
    """
    p = TradingRuleProvider(store)
    when = _dt.date(2024, 6, 14)

    # 沪市主板 golden
    sse_main = p.rules_for("600519", when, require_verified=False)
    assert sse_main is not None
    main_json = json.loads(sse_main.rule_json)
    assert main_json["daily_limit_up"] == 0.10
    assert main_json["min_buy"] == 100
    assert main_json["lot_increment"] == 100
    assert main_json["settlement_T"] == 1

    # 科创板为后续扩展；当前规则种子不命中。
    assert p.rules_for("688981", when, require_verified=False) is None

    # 撮合验证：主板 100 股整数倍；买单 150 → illegal_lot
    broker = SimBroker()
    prev_close = 50.0
    bar_normal = BarSnapshot(
        open=prev_close, high=prev_close * 1.02, low=prev_close * 0.98,
        close=prev_close, volume=1_000_000.0,
        limit_up=prev_close * 1.10, limit_down=prev_close * 0.90,
    )
    bad_lot = Order(symbol="600519", side="buy", qty=150, order_type="market")
    res = broker.match(bad_lot, bar_normal, main_json, position_qty=0)
    assert not res.filled
    assert res.reason == "illegal_lot"

    # 沪市主板买单 100（满足 min_buy）+ 正常 bar → 成交
    bar_main = BarSnapshot(
        open=prev_close, high=prev_close * 1.02, low=prev_close * 0.98,
        close=prev_close, volume=1_000_000.0,
        limit_up=prev_close * 1.10, limit_down=prev_close * 0.90,
    )
    ok_order = Order(symbol="600519", side="buy", qty=100, order_type="market")
    res2 = broker.match(ok_order, bar_main, main_json, position_qty=0)
    assert res2.filled
    assert res2.fill_qty == 100


# ===========================================================================
# 验收 2：look-ahead 0 报警（PIT 隔离）
# ===========================================================================
def test_m1_no_lookahead_leak():
    """§11 验收 2：未来 available_at 的行不进入当日决策（PIT 隔离）。

    构造 panel 含 available_at 严格 > decision_time 的"未来"行：
    - 显式 FactorContext.point 命中未来行 → LookAheadError
    - BacktestEngine.run 改未来行 close 值，当日订单/权益不变
    """
    days = [_dt.date(2024, 1, d) for d in (2, 3, 4)]
    sym = "600519"
    rows = [
        {"symbol": sym, "trade_date": d, "available_at": _day_end(d),
         "close": 10.0 + i * 0.5}
        for i, d in enumerate(days)
    ]
    # 未来行：trade_date=末日，available_at 在末日之后 3 天（look-ahead）
    leak_day = days[-1]
    rows.append({
        "symbol": sym, "trade_date": leak_day,
        "available_at": _day_end(leak_day) + _dt.timedelta(days=3),
        "close": 9999.0,
    })
    panel = pd.DataFrame(rows)
    universe = [sym]

    # 1. 显式 point 命中未来行 → LookAheadError
    # 单独构造一个 panel，该 (sym, trade_date) 行的 available_at 在 decision 之后
    future_panel = pd.DataFrame([{
        "symbol": sym, "trade_date": leak_day,
        "available_at": _day_end(leak_day) + _dt.timedelta(days=3),
        "close": 9999.0,
    }])
    decision = _day_end(leak_day)
    ctx_future = FactorContext(decision_time=decision, universe=universe,
                               snapshot_id="snap", panel=future_panel)
    with pytest.raises(LookAheadError):
        ctx_future.point(sym, "close", leak_day)

    # 2. latest（过滤语义）不返回未来行：末日可得 close 仍是 11.0，非 9999.0
    ctx = FactorContext(decision_time=decision, universe=universe,
                        snapshot_id="snap", panel=panel)
    latest = ctx.latest("close")
    assert latest.loc[sym] == pytest.approx(11.0)

    # 3. 经 BacktestEngine 跑一段：改未来行 close 值不影响权益/订单
    reg = FactorRegistry()
    reg.register(_LatestCloseFactor())
    engine = BacktestEngine(registry=reg, initial_cash=1_000_000.0)

    def _bars(panel_df):
        """按 panel 的 (symbol, trade_date) 构造 bar，close 即 panel.close。"""
        b = {}
        for _, r in panel_df.iterrows():
            c = float(r["close"])
            b[(r["symbol"], r["trade_date"])] = BarSnapshot(
                open=c, high=c * 1.02, low=c * 0.98, close=c,
                volume=1_000_000.0,
                limit_up=c * 1.10, limit_down=c * 0.90,
            )
        return b

    # 基线 panel（无未来行）
    base_rows = [
        {"symbol": sym, "trade_date": d, "available_at": _day_end(d),
         "close": 10.0 + i * 0.5}
        for i, d in enumerate(days)
    ]
    base_panel = pd.DataFrame(base_rows)
    bars = _bars(base_panel)

    class _BuyOnce(BacktestStrategy):
        required_factors = ["latest_close"]

        def __init__(self):
            self._done = False

        def on_bar(self, date, factor_panel, positions, cash, bars_today):
            if self._done:
                return []
            if sym not in factor_panel.index:
                return []
            price = float(factor_panel.loc[sym, "latest_close"])
            if pd.isna(price) or price <= 0:
                return []
            qty = int(cash * 0.3 / price // 100) * 100
            if qty < 100:
                return []
            self._done = True
            return [Order(symbol=sym, side="buy", qty=qty, order_type="market")]

    base = engine.run(
        panel=base_panel, bars=bars, trading_days=days,
        strategy=_BuyOnce(), rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_pit",
    )
    leaked = engine.run(
        panel=panel, bars=bars, trading_days=days,
        strategy=_BuyOnce(), rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_pit",
    )
    assert_series_equal(base.equity_curve, leaked.equity_curve)
    # 首日 fill_qty 不受未来行 9999 影响
    base_q = {f["symbol"]: f["fill_qty"] for f in base.fills
              if f["filled"] and f["date"] == days[0]}
    leaked_q = {f["symbol"]: f["fill_qty"] for f in leaked.fills
                if f["filled"] and f["date"] == days[0]}
    assert base_q == leaked_q


# ===========================================================================
# 验收 3：已知历史事件回放
# ===========================================================================
def test_m1_known_events_replay():
    """§11 验收 3：撮合符合已知 A 股历史事件。

    - 一字板涨停：BarSnapshot(OHLC=limit_up) → 买单 limit_up_sealed 不成交
    - T+1 回转约束：当日买入次日卖出需持仓；SimBroker sell position_qty=0
      → no_position_tplusn
    """
    broker = SimBroker()
    prev_close = 10.0
    limit_up = round(prev_close * 1.10, 2)

    # 1. 一字板涨停封死：买单不成交
    sealed_bar = BarSnapshot(
        open=limit_up, high=limit_up, low=limit_up, close=limit_up,
        volume=1_000_000.0, limit_up=limit_up, limit_down=prev_close * 0.90,
    )
    buy = Order(symbol="600519", side="buy", qty=100, order_type="market")
    res = broker.match(buy, sealed_bar, RULE_MAIN, position_qty=0)
    assert not res.filled
    assert res.reason == "limit_up_sealed"

    # 2. T+1 回转约束：无持仓卖出 → no_position_tplusn
    normal_bar = BarSnapshot(
        open=prev_close, high=prev_close * 1.02, low=prev_close * 0.98,
        close=prev_close, volume=1_000_000.0,
        limit_up=prev_close * 1.10, limit_down=prev_close * 0.90,
    )
    sell_no_pos = Order(symbol="600519", side="sell", qty=100, order_type="market")
    res2 = broker.match(sell_no_pos, normal_bar, RULE_MAIN, position_qty=0)
    assert not res2.filled
    assert res2.reason == "no_position_tplusn"

    # 有持仓时卖出可成交（T+1 由调用方保证 position_qty 已落仓）
    sell_with_pos = Order(symbol="600519", side="sell", qty=100, order_type="market")
    res3 = broker.match(sell_with_pos, normal_bar, RULE_MAIN, position_qty=100)
    assert res3.filled
    assert res3.fill_qty == 100


# ===========================================================================
# 验收 4：同 snapshot 二次运行一致
# ===========================================================================
def test_m1_reproducibility():
    """§11 验收 4：同 panel+bars+strategy+snapshot_id 跑两次 → equity_curve 与 fills 完全相等。"""
    panel, bars, days = _synth_market(n_symbols=3, n_days=10, seed=_SEED)
    reg = FactorRegistry()
    reg.register(MomentumFactor(window=3))
    reg.register(_LatestCloseFactor())
    engine = BacktestEngine(registry=reg, initial_cash=1_000_000.0)

    r1 = engine.run(
        panel=panel, bars=bars, trading_days=days,
        strategy=_MomentumTopN(top_n=1, momentum_window=3),
        rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_repro",
    )
    r2 = engine.run(
        panel=panel, bars=bars, trading_days=days,
        strategy=_MomentumTopN(top_n=1, momentum_window=3),
        rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_repro",
    )
    assert_series_equal(r1.equity_curve, r2.equity_curve)
    assert len(r1.fills) == len(r2.fills)
    for a, b in zip(r1.fills, r2.fills):
        assert a["symbol"] == b["symbol"]
        assert a["filled"] == b["filled"]
        assert a["fill_qty"] == b["fill_qty"]
        assert a["fill_price"] == b["fill_price"]


# ===========================================================================
# 验收 5：连续 3 年（约 750 交易日）无异常
# ===========================================================================
def test_m1_multi_year_run():
    """§11 验收 5：~750 交易日（3 年×250）合成 panel，简单动量策略跑通无异常。

    断言：无抛出、equity_curve 长度=交易日数、权益无 NaN。
    """
    panel, bars, days = _synth_market(n_symbols=4, n_days=250 * 3, seed=_SEED)
    reg = FactorRegistry()
    reg.register(MomentumFactor(window=20))
    reg.register(_LatestCloseFactor())
    engine = BacktestEngine(registry=reg, initial_cash=1_000_000.0)

    result = engine.run(
        panel=panel, bars=bars, trading_days=days,
        strategy=_MomentumTopN(top_n=2),
        rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_multi_year",
    )
    assert len(result.equity_curve) == len(days)
    assert not result.equity_curve.isna().any()
    # 全部权益为有限正数（不会因 NaN/inf 异常崩塌）
    assert (result.equity_curve > 0).all()


# ===========================================================================
# 验收 6：基准绩效 sanity
# ===========================================================================
def test_m1_benchmark_sanity():
    """§11 验收 6：合成上涨市（close 单调涨），等权买入持有 vs buy-and-hold 基准。

    断言：策略终值 >= 基准终值 * 0.9（留摩擦余量）；策略终值 > 0 且权益曲线非全 NaN。
    """
    # 单调上涨市：close 每日涨 0.1%
    panel, bars, days = _synth_monotonic_up(n_symbols=3, n_days=30)
    reg = FactorRegistry()
    reg.register(_LatestCloseFactor())
    engine = BacktestEngine(registry=reg, initial_cash=1_000_000.0)

    result = engine.run(
        panel=panel, bars=bars, trading_days=days,
        strategy=_BuyAndHoldEqual(),
        rule_json_fn=lambda s, d: RULE_MAIN,
        snapshot_id="snap_bench",
    )
    assert not result.equity_curve.isna().any()
    final_equity = float(result.equity_curve.iloc[-1])
    assert final_equity > 0

    # buy-and-hold 基准：等权买入持有全部 symbol，无摩擦
    bench = _buy_and_hold_benchmark(panel, days, initial=1_000_000.0)
    # 策略受摩擦与 lot 对齐影响，允许 10% 劣化
    assert final_equity >= bench * 0.9


# ===========================================================================
# 合成数据与辅助策略
# ===========================================================================
def _synth_market(n_symbols: int, n_days: int, seed: int):
    """合成 N symbol × T day panel：close 带趋势 + 噪声，固定 seed。

    available_at = trade_date 当日 16:00（PIT 安全）。bars 用当日 close 简化。
    """
    rng = np.random.default_rng(seed)
    start = _dt.date(2021, 1, 4)
    days = [_start_to_date(start, i) for i in range(n_days)]
    symbols = [f"60000{i}.SH" for i in range(n_symbols)]

    rows = []
    bars = {}
    for j, sym in enumerate(symbols):
        # 每 symbol 不同起始价与漂移，加固定噪声
        price = 20.0 + j * 5.0
        drift = rng.uniform(-0.001, 0.002)
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


def _synth_monotonic_up(n_symbols: int, n_days: int):
    """合成单调上涨市：close 每日涨 0.1%，无噪声。"""
    start = _dt.date(2021, 1, 4)
    days = [_start_to_date(start, i) for i in range(n_days)]
    symbols = [f"60000{i}.SH" for i in range(n_symbols)]
    rows = []
    bars = {}
    for j, sym in enumerate(symbols):
        price = 20.0 + j * 5.0
        for i, d in enumerate(days):
            c = round(price * (1.001 ** i), 2)
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
    """start + i 个工作日（跳过周末，简化无节假日）。"""
    d = start
    stepped = 0
    while stepped < i:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            stepped += 1
    return d


class _LatestCloseFactor:
    """每 symbol PIT 可得最新 close（duck typing 满足 Factor Protocol）。"""

    name = "latest_close"
    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        return ctx.latest("close")


class _MomentumTopN(BacktestStrategy):
    """动量 top-N 等权市价买，首日下单后持有。

    momentum_window 指定动量窗口，required_factors 据此动态命名。
    """

    def __init__(self, top_n: int = 1, momentum_window: int = 20):
        self._top_n = top_n
        self._ordered = False
        self.required_factors = [f"momentum_{momentum_window}", "latest_close"]

    def on_bar(self, date, factor_panel, positions, cash, bars_today):
        if self._ordered:
            return []
        if factor_panel.empty or "momentum_20" not in factor_panel.columns:
            return []
        mom = factor_panel["momentum_20"].dropna()
        if mom.empty:
            return []
        tops = mom.sort_values(ascending=False).head(self._top_n).index.tolist()
        orders = []
        per_target = cash / max(len(tops), 1) * 0.95
        for sym in tops:
            price = float(factor_panel.loc[sym, "latest_close"])
            if pd.isna(price) or price <= 0:
                continue
            qty = int(per_target / price // 100) * 100
            if qty < RULE_MAIN["min_buy"]:
                continue
            orders.append(Order(symbol=sym, side="buy", qty=qty, order_type="market"))
        self._ordered = True
        return orders


class _BuyAndHoldEqual(BacktestStrategy):
    """首日等权市价买入全部 universe 并持有至末日。"""

    required_factors = ["latest_close"]

    def __init__(self):
        self._ordered = False

    def on_bar(self, date, factor_panel, positions, cash, bars_today):
        if self._ordered:
            return []
        orders = []
        syms = [s for s in factor_panel.index
                if not pd.isna(factor_panel.loc[s, "latest_close"])]
        per = cash / max(len(syms), 1) * 0.95
        for sym in syms:
            price = float(factor_panel.loc[sym, "latest_close"])
            qty = int(per / price // 100) * 100
            if qty < RULE_MAIN["min_buy"]:
                continue
            orders.append(Order(symbol=sym, side="buy", qty=qty, order_type="market"))
        self._ordered = True
        return orders


def _buy_and_hold_benchmark(panel: pd.DataFrame, days: list, initial: float) -> float:
    """等权买入持有全部 symbol 的无摩擦末日市值（基准）。"""
    syms = sorted(panel["symbol"].unique())
    per = initial / len(syms)
    first_day = days[0]
    last_day = days[-1]
    total = 0.0
    for sym in syms:
        p0 = float(panel[(panel["symbol"] == sym)
                         & (panel["trade_date"] == first_day)]["close"].iloc[0])
        p1 = float(panel[(panel["symbol"] == sym)
                         & (panel["trade_date"] == last_day)]["close"].iloc[0])
        shares = per / p0
        total += shares * p1
    return total
