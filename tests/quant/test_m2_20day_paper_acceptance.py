"""M2 连续 20 交易日模拟盘验收。

目标：把短程 mock 闭环升级为 20 个交易日的日终验收：
mock bars → FactorRegistry → StrategyRunner → SimBrokerLive → on_fill →
日终 reconcile。全部数据固定 seed，测试可重复。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.backtest.engine import Position
from quant.backtest.sim_broker import BarSnapshot, Order
from quant.clock import BacktestClock
from quant.execution.reconcile import reconcile
from quant.execution.sim_broker_live import SimBrokerLive
from quant.factor.factors.momentum import MomentumFactor
from quant.factor.registry import FactorRegistry
from quant.strategy.context import BarContext, FillContext
from quant.strategy.runner import StrategyRunner
from quant.strategy.signal import Signal


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


@dataclass
class PaperAccount:
    account_id: str
    broker: SimBrokerLive
    runner: StrategyRunner
    strategy: "TopMomentumStrategy"
    daily_snapshots: list[dict] = field(default_factory=list)
    daily_reconcile: list[float] = field(default_factory=list)


class TopMomentumStrategy:
    name = "top_momentum"
    required_factors = ["momentum_3"]

    def __init__(self) -> None:
        self.fill_contexts: list[FillContext] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        if "momentum_3" not in ctx.factor_panel.columns:
            return []
        scores = ctx.factor_panel["momentum_3"].dropna()
        if scores.empty:
            return []
        symbol = str(scores.idxmax())
        current_qty = ctx.positions.get(symbol, Position()).qty
        if current_qty >= 300:
            return []
        return [Signal(symbol=symbol, direction=1, strength=float(scores.loc[symbol]))]

    def on_fill(self, ctx: FillContext) -> None:
        self.fill_contexts.append(ctx)


class CrashOnFillStrategy:
    name = "crash_on_fill"
    required_factors: list[str] = []

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        return []

    def on_fill(self, ctx: FillContext) -> None:
        raise RuntimeError("isolated fill failure")


def test_m2_runs_20_trading_days_with_reconcile_and_account_isolation() -> None:
    panel, bars, trading_days = _synthetic_market(n_symbols=5, n_days=24, seed=20240616)
    acceptance_days = trading_days[4:24]
    assert len(acceptance_days) == 20

    registry = FactorRegistry()
    registry.register(MomentumFactor(window=3))

    accounts = [_make_account("acct-a"), _make_account("acct-b")]
    universe = sorted(panel["symbol"].unique().tolist())

    for day_index, day in enumerate(acceptance_days, start=1):
        decision_time = dt.datetime.combine(day, dt.time(15, 0))
        factor_panel = registry.compute_panel(
            names=["momentum_3"],
            t=decision_time,
            universe=universe,
            snapshot_id="m2_20day_acceptance",
            panel=panel,
        )

        for account in accounts:
            fills_before = account.broker.fills()
            positions_before = _positions_as_objects(account.broker.positions())
            ctx = BarContext(
                bar=bars[(universe[0], day)],
                symbol=universe[0],
                decision_time=decision_time,
                clock=BacktestClock(decision_time),
                account_id=account.account_id,
                positions=positions_before,
                factor_panel=factor_panel,
                rules=RULE_MAIN,
                trace_id=f"{account.account_id}-{day.isoformat()}",
            )

            signals = account.runner.run(ctx)
            for signal in signals:
                if signal.direction <= 0:
                    continue
                bar = bars[(signal.symbol, day)]
                account.broker.set_bar(bar)
                client_order_id = f"paper-{day_index:02d}-{signal.symbol}"
                order = Order(
                    symbol=signal.symbol,
                    side="buy",
                    qty=100,
                    order_type="limit",
                    price=round(bar.close, 2),
                )
                account.broker.place(order, client_order_id=client_order_id)

            fills_after = account.broker.fills()
            new_fills = {
                oid: fill
                for oid, fill in fills_after.items()
                if oid not in fills_before
            }
            account.runner.on_fills(
                lambda fill, account=account, decision_time=decision_time: FillContext(
                    fill=fill,
                    account_id=account.account_id,
                    positions=_positions_as_objects(account.broker.positions()),
                    decision_time=decision_time,
                    trace_id=f"{account.account_id}-{day.isoformat()}-fill",
                ),
                list(new_fills.values()),
            )

            result = reconcile(
                local_fills=_reconcile_payload(fills_after),
                broker_fills=_reconcile_payload(account.broker.fills()),
                total_orders=max(len(fills_after), 1_000),
                account_id=account.account_id,
                threshold=0.001,
            )
            account.daily_reconcile.append(result.diff_rate)
            account.daily_snapshots.append(
                {
                    "day": day,
                    "positions": account.broker.positions(),
                    "fills": dict(fills_after),
                }
            )

    for account in accounts:
        assert len(account.daily_snapshots) == 20
        assert len(account.daily_reconcile) == 20
        assert max(account.daily_reconcile) < 0.001
        assert account.broker.positions()
        assert account.broker.fills()
        assert len(account.strategy.fill_contexts) == len(account.broker.fills())

    assert accounts[0].broker.positions() == accounts[1].broker.positions()
    assert accounts[0].broker.fills().keys() == accounts[1].broker.fills().keys()
    assert accounts[0].broker.fills() is not accounts[1].broker.fills()


def _make_account(account_id: str) -> PaperAccount:
    broker = SimBrokerLive(rule_json_fn=lambda: RULE_MAIN)
    runner = StrategyRunner()
    strategy = TopMomentumStrategy()
    runner.register(strategy)
    runner.register(CrashOnFillStrategy())
    return PaperAccount(account_id=account_id, broker=broker, runner=runner, strategy=strategy)


def _synthetic_market(n_symbols: int, n_days: int, seed: int):
    rng = np.random.default_rng(seed)
    start = dt.date(2024, 1, 2)
    days = _weekdays(start, n_days)
    symbols = [f"6000{i:02d}" for i in range(n_symbols)]
    rows = []
    bars = {}

    for idx, symbol in enumerate(symbols):
        price = 10.0 + idx * 4.0
        drift = 0.002 + idx * 0.0005
        noise = rng.normal(0, 0.001, size=n_days)
        closes = price * np.cumprod(1 + drift + noise)
        for day, close_raw in zip(days, closes):
            close = round(float(close_raw), 2)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": day,
                    "available_at": dt.datetime.combine(day, dt.time(15, 0)),
                    "close": close,
                }
            )
            bars[(symbol, day)] = BarSnapshot(
                open=close,
                high=round(close * 1.01, 2),
                low=round(close * 0.99, 2),
                close=close,
                volume=1_000_000.0,
                limit_up=round(close * 1.1, 2),
                limit_down=round(close * 0.9, 2),
            )

    return pd.DataFrame(rows), bars, days


def _weekdays(start: dt.date, n: int) -> list[dt.date]:
    days = []
    cur = start
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur += dt.timedelta(days=1)
    return days


def _positions_as_objects(raw: dict[str, int]) -> dict[str, Position]:
    return {symbol: Position(qty=qty, avg_cost=0.0) for symbol, qty in raw.items()}


def _reconcile_payload(fills: dict) -> dict[str, dict]:
    return {
        order_id: {
            "qty": fill.fill_qty,
            "price": fill.fill_price,
            "status": "filled" if fill.filled else "pending",
        }
        for order_id, fill in fills.items()
    }
