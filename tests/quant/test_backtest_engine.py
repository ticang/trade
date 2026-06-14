"""BacktestEngine 事件循环测试（设计 v0.5 §4.7 / §7.2 / §4.7.6）。

覆盖事件驱动回测的关键属性：
- run 返回 equity_curve（index=trade_date）与 fills / final_positions
- 买入扣减现金；成交更新持仓 qty
- 权益 = cash + Σ持仓按当日 close 的市值（mark-to-market）
- 同 snapshot 绑定下二次运行完全可复现（equity_curve assert_series_equal）
- PIT 强制：panel 含 available_at 在未来的行不泄漏到当日决策

TDD：本文件先于 engine.py 编写，import 失败为预期红线。
风控（RiskEngine）在 D 阶段做，C3 不接；on_bar 直接产单撮合。
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from quant.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestStrategy,
    Position,
)
from quant.backtest.sim_broker import BarSnapshot, Order
from quant.factor.context import FactorContext
from quant.factor.registry import FactorRegistry

# ---------------------------------------------------------------------------
# 合成数据：3 symbol × 5 交易日
# ---------------------------------------------------------------------------
# close 单调递增；available_at = trade_date 当日 16:00（收盘后可得，PIT 安全）
DAYS = [_dt.date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
SYMBOLS = ["000001.SZ", "600000.SH", "300001.SZ"]
# 每 symbol 的起始 close 与日步长
_BASE = {"000001.SZ": 10.0, "600000.SH": 20.0, "300001.SZ": 30.0}

# rule_json 种子：沪市主板股票（与 test_sim_broker 一致）
RULE_JSON = {
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


def _day_end(dt: _dt.date) -> _dt.datetime:
    """trade_date 当日 16:00（收盘后决策时刻）。"""
    return _dt.datetime.combine(dt, _dt.time(hour=16, minute=0))


def _build_panel(future_close_for: dict[str, float] | None = None) -> pd.DataFrame:
    """构造长格式 panel。

    每 symbol 每 trade_date 一行：available_at = trade_date 16:00，close 单调递增。
    future_close_for：可选，追加一行 available_at 在最后一个交易日之后的"未来"数据
    （用于 PIT 泄漏测试；正常回测应过滤，不影响当日决策）。
    """
    rows: list[dict] = []
    for sym in SYMBOLS:
        base = _BASE[sym]
        for i, d in enumerate(DAYS):
            rows.append({
                "symbol": sym,
                "trade_date": d,
                "available_at": _day_end(d),
                "close": round(base + i * 0.5, 2),
            })
    if future_close_for:
        # 未来行：trade_date 为最后一个交易日，但 available_at 在其之后（look-ahead）
        leak_day = DAYS[-1]
        for sym, close in future_close_for.items():
            rows.append({
                "symbol": sym,
                "trade_date": leak_day,
                "available_at": _day_end(leak_day) + _dt.timedelta(days=3),
                "close": close,
            })
    return pd.DataFrame(rows)


def _build_bars() -> dict[tuple[str, _dt.date], BarSnapshot]:
    """构造 bars 字典：key=(symbol, trade_date)，limit_up/down 用 ±10%。

    涨跌停价以当日 close 为锚简化（与 close 同基；M1 不要求精确前收）。
    成交量充足（量比封顶不阻断 min_buy）。
    """
    bars: dict[tuple[str, _dt.date], BarSnapshot] = {}
    panel = _build_panel()
    for _, r in panel.iterrows():
        close = float(r["close"])
        bars[(r["symbol"], r["trade_date"])] = BarSnapshot(
            open=close,
            high=close * 1.02,
            low=close * 0.98,
            close=close,
            volume=1_000_000.0,
            limit_up=close * 1.10,
            limit_down=close * 0.90,
        )
    return bars


# ---------------------------------------------------------------------------
# 假因子：每 symbol PIT 可得最新 close（duck typing 满足 Factor Protocol）
# ---------------------------------------------------------------------------
class _LatestCloseFactor:
    name = "latest_close"
    factor_version = "v1"
    inputs = ["close"]

    def compute(self, ctx: FactorContext) -> pd.Series:
        return ctx.latest("close")


# ---------------------------------------------------------------------------
# 简单策略：第 1 个交易日，等权买入 2 个 symbol（市价单，lot 对齐）
# ---------------------------------------------------------------------------
class _BuyTwoOnDay1(BacktestStrategy):
    """首日等权买入前 2 个 symbol 的市价单。

    qty = floor(cash * 0.4 / price / lot) * lot，向 lot 对齐并封顶可用现金。
    """
    required_factors = ["latest_close"]

    def __init__(self, targets: list[str] | None = None) -> None:
        self._targets = targets or SYMBOLS[:2]
        self._ordered = False

    def on_bar(self, date, factor_panel, positions, cash, bars_today):
        if self._ordered:
            return []
        orders: list[Order] = []
        # 首日：据 factor_panel 中可得 close 下单（不直接读 bars，确保走因子面板）
        for sym in self._targets:
            if sym not in factor_panel.index:
                continue
            price = float(factor_panel.loc[sym, "latest_close"])
            if pd.isna(price) or price <= 0:
                continue
            raw = cash * 0.4 / price
            qty = int(raw // RULE_JSON["lot_increment"]) * RULE_JSON["lot_increment"]
            if qty < RULE_JSON["min_buy"]:
                continue
            orders.append(Order(symbol=sym, side="buy", qty=qty, order_type="market"))
        self._ordered = True
        return orders


# ---------------------------------------------------------------------------
# 公共装配
# ---------------------------------------------------------------------------
@pytest.fixture
def registry() -> FactorRegistry:
    reg = FactorRegistry()
    reg.register(_LatestCloseFactor())
    return reg


def _rule_json_fn(symbol, date):  # noqa: ANN001 -- M1 简化为固定规则
    return RULE_JSON


def _make_engine(registry: FactorRegistry) -> BacktestEngine:
    return BacktestEngine(registry=registry, initial_cash=1_000_000.0)


# ---------------------------------------------------------------------------
# 1. run 返回 equity_curve（长度 = 交易日数）与 final_positions（买入发生）
# ---------------------------------------------------------------------------
def test_engine_runs_and_returns_equity(registry: FactorRegistry):
    engine = _make_engine(registry)
    result = engine.run(
        panel=_build_panel(),
        bars=_build_bars(),
        trading_days=DAYS,
        strategy=_BuyTwoOnDay1(),
        rule_json_fn=_rule_json_fn,
    )
    assert isinstance(result, BacktestResult)
    assert isinstance(result.equity_curve, pd.Series)
    assert len(result.equity_curve) == len(DAYS)
    assert list(result.equity_curve.index) == DAYS
    # 首日买入 2 个 symbol → final_positions 非空
    assert len(result.final_positions) >= 1
    assert any(p.qty > 0 for p in result.final_positions.values())
    # fills 有记录
    assert len(result.fills) >= 1


# ---------------------------------------------------------------------------
# 2. 买入扣减现金：成交后 cash < initial_cash
# ---------------------------------------------------------------------------
def test_cash_decreases_on_buy(registry: FactorRegistry):
    engine = _make_engine(registry)
    result = engine.run(
        panel=_build_panel(),
        bars=_build_bars(),
        trading_days=DAYS,
        strategy=_BuyTwoOnDay1(),
        rule_json_fn=_rule_json_fn,
    )
    # 买入成交扣现金：从 fills 累计 cost_total，剩余现金应严格小于初始现金
    buys = [f for f in result.fills if f["filled"] and f["side"] == "buy"]
    assert len(buys) >= 1
    spent = sum(f["cost_total"] for f in buys)
    remaining_cash = engine.initial_cash - spent
    assert remaining_cash < engine.initial_cash
    assert spent > 0


# ---------------------------------------------------------------------------
# 3. 成交 symbol 的 positions[symbol].qty > 0
# ---------------------------------------------------------------------------
def test_position_updated(registry: FactorRegistry):
    engine = _make_engine(registry)
    result = engine.run(
        panel=_build_panel(),
        bars=_build_bars(),
        trading_days=DAYS,
        strategy=_BuyTwoOnDay1(),
        rule_json_fn=_rule_json_fn,
    )
    # 策略下单的 2 个 symbol 应有持仓
    bought = [sym for sym in SYMBOLS[:2] if sym in result.final_positions]
    assert len(bought) >= 1
    for sym in bought:
        assert result.final_positions[sym].qty > 0
        assert result.final_positions[sym].avg_cost > 0


# ---------------------------------------------------------------------------
# 4. 权益 = cash + Σ持仓按当日 close 的市值（mark-to-market）
# ---------------------------------------------------------------------------
def test_equity_marked_to_market(registry: FactorRegistry):
    engine = _make_engine(registry)
    bars = _build_bars()
    result = engine.run(
        panel=_build_panel(),
        bars=bars,
        trading_days=DAYS,
        strategy=_BuyTwoOnDay1(),
        rule_json_fn=_rule_json_fn,
    )
    # 末日的权益手算：cash + Σ qty * close（用 bars 末日 close）
    last_day = DAYS[-1]
    cash = 0.0
    # 从 fills 反推 cash 不可靠（含多笔），改用：直接断言每个交易日权益 = 该日
    # mark-to-market。重新手算每日 cash 与持仓。
    # —— 这里用更直接的断言：对每个交易日重算权益并比对 equity_curve。
    cash = float(engine.initial_cash)
    holdings: dict[str, int] = {}
    # 重放 fills（按日期分组）还原 cash/持仓，逐日比对
    fills_by_date: dict[_dt.date, list] = {}
    for f in result.fills:
        fills_by_date.setdefault(f["date"], []).append(f)
    for d in DAYS:
        for f in fills_by_date.get(d, []):
            if not f["filled"]:
                continue
            cost = f["cost_total"]
            if f["side"] == "buy":
                cash -= cost
                holdings[f["symbol"]] = holdings.get(f["symbol"], 0) + f["fill_qty"]
            else:
                cash += cost
                holdings[f["symbol"]] -= f["fill_qty"]
        mkt = sum(q * bars[(s, d)].close for s, q in holdings.items() if q != 0)
        expected_equity = cash + mkt
        assert result.equity_curve.loc[d] == pytest.approx(expected_equity, rel=1e-9)


# ---------------------------------------------------------------------------
# 5. 同 panel+bars+strategy+snapshot_id 二次运行 → equity_curve 完全相等
# ---------------------------------------------------------------------------
def test_reproducibility_same_snapshot(registry: FactorRegistry):
    engine = _make_engine(registry)
    panel = _build_panel()
    bars = _build_bars()
    r1 = engine.run(
        panel=panel, bars=bars, trading_days=DAYS,
        strategy=_BuyTwoOnDay1(), rule_json_fn=_rule_json_fn,
        snapshot_id="snap_repro",
    )
    r2 = engine.run(
        panel=panel, bars=bars, trading_days=DAYS,
        strategy=_BuyTwoOnDay1(), rule_json_fn=_rule_json_fn,
        snapshot_id="snap_repro",
    )
    assert_series_equal(r1.equity_curve, r2.equity_curve)
    assert len(r1.fills) == len(r2.fills)


# ---------------------------------------------------------------------------
# 6. PIT 强制：panel 含 available_at > 当日的未来行，engine 经 FactorContext 过滤不泄漏
# ---------------------------------------------------------------------------
def test_pit_respected(registry: FactorRegistry):
    """未来行（available_at 在末日之后）不应进入末日决策。

    断言：含/不含未来行两次运行的 equity_curve 与 fills 完全一致——若 PIT 泄漏，
    未来 close 会进入 factor_panel.latest_close，策略按更高/更低 close 重算 qty。
    """
    engine = _make_engine(registry)
    bars = _build_bars()

    # 基线：无未来行
    base = engine.run(
        panel=_build_panel(),
        bars=bars, trading_days=DAYS,
        strategy=_BuyTwoOnDay1(), rule_json_fn=_rule_json_fn,
        snapshot_id="snap_pit",
    )
    # 含未来行：末日 close 被改成离谱的值（available_at 在末日之后）
    leaked = engine.run(
        panel=_build_panel(future_close_for={"000001.SZ": 9999.0}),
        bars=bars, trading_days=DAYS,
        strategy=_BuyTwoOnDay1(), rule_json_fn=_rule_json_fn,
        snapshot_id="snap_pit",
    )
    assert_series_equal(base.equity_curve, leaked.equity_curve)
    assert len(base.fills) == len(leaked.fills)
    # 关键：未来行未进入首日 factor_panel —— 否则首日 fill_qty 会变（按 9999 重算）
    base_day1_qty = {
        f["symbol"]: f["fill_qty"] for f in base.fills if f["filled"] and f["date"] == DAYS[0]
    }
    leaked_day1_qty = {
        f["symbol"]: f["fill_qty"] for f in leaked.fills if f["filled"] and f["date"] == DAYS[0]
    }
    assert base_day1_qty == leaked_day1_qty
