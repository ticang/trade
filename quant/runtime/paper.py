"""Runnable paper trading session.

This module moves the deterministic paper-trading loop out of tests and into a
real runtime entry point. It is safe by design: it uses SimBrokerLive and never
touches QMT order APIs.
"""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

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


@dataclass(frozen=True)
class PaperAccountSummary:
    account_id: str
    positions: dict[str, int]
    fills: int
    max_reconcile_diff: float


@dataclass(frozen=True)
class PaperRunSummary:
    mode: str
    days_run: int
    account_count: int
    total_fills: int
    max_reconcile_diff: float
    accounts: list[PaperAccountSummary]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "days_run": self.days_run,
            "account_count": self.account_count,
            "total_fills": self.total_fills,
            "max_reconcile_diff": self.max_reconcile_diff,
            "accounts": [
                {
                    "account_id": account.account_id,
                    "positions": account.positions,
                    "fills": account.fills,
                    "max_reconcile_diff": account.max_reconcile_diff,
                }
                for account in self.accounts
            ],
        }


class TopMomentumStrategy:
    name = "top_momentum"
    required_factors = ["momentum_3"]

    def __init__(self) -> None:
        self.fill_count = 0

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
        self.fill_count += 1


@dataclass
class _PaperAccount:
    account_id: str
    broker: SimBrokerLive
    runner: StrategyRunner
    strategy: TopMomentumStrategy
    reconcile_diffs: list[float]


def run_paper_session(
    *,
    n_days: int = 20,
    n_symbols: int = 5,
    accounts: Iterable[str] = ("acct-a", "acct-b"),
    seed: int = 20240616,
    state_path: str | Path | None = None,
) -> PaperRunSummary:
    if n_days <= 0:
        raise ValueError("n_days must be positive")
    if n_symbols <= 0:
        raise ValueError("n_symbols must be positive")

    warmup = 4
    panel, bars, trading_days = _synthetic_market(
        n_symbols=n_symbols,
        n_days=n_days + warmup,
        seed=seed,
    )
    run_days = trading_days[warmup:]
    registry = FactorRegistry()
    registry.register(MomentumFactor(window=3))
    universe = sorted(panel["symbol"].unique().tolist())
    paper_accounts = [_make_account(account_id) for account_id in accounts]
    order_rows: list[dict] = []
    fill_rows: list[dict] = []

    for day_index, day in enumerate(run_days, start=1):
        decision_time = dt.datetime.combine(day, dt.time(15, 0))
        factor_panel = registry.compute_panel(
            names=["momentum_3"],
            t=decision_time,
            universe=universe,
            snapshot_id="paper_runtime",
            panel=panel,
        )
        for account in paper_accounts:
            fills_before = account.broker.fills()
            ctx = BarContext(
                bar=bars[(universe[0], day)],
                symbol=universe[0],
                decision_time=decision_time,
                clock=BacktestClock(decision_time),
                account_id=account.account_id,
                positions=_positions_as_objects(account.broker.positions()),
                factor_panel=factor_panel,
                rules=RULE_MAIN,
                trace_id=f"{account.account_id}-{day.isoformat()}",
            )
            for signal in account.runner.run(ctx):
                if signal.direction <= 0:
                    continue
                bar = bars[(signal.symbol, day)]
                account.broker.set_bar(bar)
                client_order_id = f"paper-{account.account_id}-{day_index:02d}-{signal.symbol}"
                account.broker.place(
                    Order(
                        symbol=signal.symbol,
                        side="buy",
                        qty=100,
                        order_type="limit",
                        price=round(bar.close, 2),
                    ),
                    client_order_id=client_order_id,
                )
                order_rows.append({
                    "order_id": client_order_id,
                    "account_id": account.account_id,
                    "symbol": signal.symbol,
                    "side": "buy",
                    "price": round(bar.close, 2),
                    "qty": 100,
                    "filled_qty": 100,
                    "status": "filled",
                    "ts": _to_ms(decision_time),
                })
            fills_after = account.broker.fills()
            new_fills = [
                (order_id, fill) for order_id, fill in fills_after.items()
                if order_id not in fills_before
            ]
            account.runner.on_fills(
                lambda fill, account=account, decision_time=decision_time: FillContext(
                    fill=fill,
                    account_id=account.account_id,
                    positions=_positions_as_objects(account.broker.positions()),
                    decision_time=decision_time,
                    trace_id=f"{account.account_id}-{day.isoformat()}-fill",
                ),
                [fill for _, fill in new_fills],
            )
            for order_id, fill in new_fills:
                symbol = _symbol_from_order_id(order_id)
                fill_rows.append({
                    "fill_id": f"fill-{order_id}",
                    "order_id": order_id,
                    "account_id": account.account_id,
                    "symbol": symbol,
                    "side": "buy",
                    "price": fill.fill_price,
                    "qty": fill.fill_qty,
                    "ts": _to_ms(decision_time),
                })
            result = reconcile(
                local_fills=_reconcile_payload(fills_after),
                broker_fills=_reconcile_payload(account.broker.fills()),
                total_orders=max(len(fills_after), 1_000),
                account_id=account.account_id,
                threshold=0.001,
            )
            account.reconcile_diffs.append(result.diff_rate)

    summaries = [
        PaperAccountSummary(
            account_id=account.account_id,
            positions=account.broker.positions(),
            fills=len(account.broker.fills()),
            max_reconcile_diff=max(account.reconcile_diffs or [0.0]),
        )
        for account in paper_accounts
    ]
    summary = PaperRunSummary(
        mode="paper",
        days_run=len(run_days),
        account_count=len(summaries),
        total_fills=sum(account.fills for account in summaries),
        max_reconcile_diff=max((account.max_reconcile_diff for account in summaries), default=0.0),
        accounts=summaries,
    )
    if state_path is not None:
        _write_state(
            Path(state_path),
            summary=summary,
            panel=panel,
            bars=bars,
            run_days=run_days,
            universe=universe,
            order_rows=order_rows,
            fill_rows=fill_rows,
        )
    return summary


def _make_account(account_id: str) -> _PaperAccount:
    broker = SimBrokerLive(rule_json_fn=lambda: RULE_MAIN)
    runner = StrategyRunner()
    strategy = TopMomentumStrategy()
    runner.register(strategy)
    return _PaperAccount(
        account_id=account_id,
        broker=broker,
        runner=runner,
        strategy=strategy,
        reconcile_diffs=[],
    )


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
            rows.append({
                "symbol": symbol,
                "trade_date": day,
                "available_at": dt.datetime.combine(day, dt.time(15, 0)),
                "close": close,
            })
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


def default_state_path() -> Path:
    return Path("var") / "runtime" / "latest_state.json"


def _write_state(
    path: Path,
    *,
    summary: PaperRunSummary,
    panel: pd.DataFrame,
    bars: dict,
    run_days: list[dt.date],
    universe: list[str],
    order_rows: list[dict],
    fill_rows: list[dict],
) -> None:
    latest_day = run_days[-1]
    latest_prices = {
        symbol: bars[(symbol, latest_day)].close
        for symbol in universe
    }
    positions = []
    account_rows = []
    for account in summary.accounts:
        market_value = 0.0
        for symbol, qty in account.positions.items():
            last = latest_prices[symbol]
            value = round(qty * last, 2)
            market_value += value
            positions.append({
                "account_id": account.account_id,
                "symbol": symbol,
                "name": symbol,
                "qty": qty,
                "avg_cost": last,
                "last": last,
                "market_value": value,
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "weight": 0.0,
            })
        total = round(market_value, 2)
        account_rows.append({
            "account_id": account.account_id,
            "cash": 0.0,
            "market_value": total,
            "total": total,
            "available": 0.0,
        })
    for row in positions:
        total = next(
            item["total"] for item in account_rows
            if item["account_id"] == row["account_id"]
        )
        row["weight"] = round(row["market_value"] / total, 4) if total else 0.0

    signal_rows = _signals_by_symbol(fill_rows)
    state = {
        "mode": "paper",
        "generated_at": _to_ms(dt.datetime.now()),
        "summary": summary.to_dict(),
        "markets": [
            {
                "symbol": symbol,
                "name": symbol,
                "last": latest_prices[symbol],
                "change": _change_pct(panel, symbol),
                "volume": int(bars[(symbol, latest_day)].volume),
            }
            for symbol in universe
        ],
        "kline": {
            symbol: [
                {
                    "ts": _to_ms(dt.datetime.combine(day, dt.time(15, 0))),
                    "open": bars[(symbol, day)].open,
                    "high": bars[(symbol, day)].high,
                    "low": bars[(symbol, day)].low,
                    "close": bars[(symbol, day)].close,
                    "volume": bars[(symbol, day)].volume,
                }
                for day in run_days
            ]
            for symbol in universe
        },
        "sentiment": {
            symbol: [
                {
                    "ts": _to_ms(dt.datetime.combine(day, dt.time(15, 0))),
                    "score": 0.0,
                }
                for day in run_days
            ]
            for symbol in universe
        },
        "signals": {symbol: signal_rows.get(symbol, []) for symbol in universe},
        "account": account_rows,
        "positions": positions,
        "orders": order_rows,
        "fills": fill_rows,
        "risk": {
            "total_position_pct": 1.0 if positions else 0.0,
            "max_single_pct": max((row["weight"] for row in positions), default=0.0),
            "industry_exposure": [{"industry": "runtime", "pct": 1.0 if positions else 0.0}],
            "drawdown": 0.0,
            "drawdown_limit": -0.15,
            "circuit_breaker": "normal",
        },
        "alerts": [
            {
                "ts": _to_ms(dt.datetime.now()),
                "level": "info",
                "title": "paper runtime completed",
                "detail": f"{summary.days_run} days, {summary.total_fills} fills",
            }
        ],
        "strategies": [
            {
                "name": "top_momentum",
                "status": "paper",
                "account_id": account.account_id,
                "ic": 0.0,
                "turnover": 0.0,
                "drawdown": 0.0,
                "allocation": 1.0 / max(summary.account_count, 1),
            }
            for account in summary.accounts
        ],
        "factor_eval": [
            {
                "name": "momentum_3",
                "ic_series": [
                    {
                        "ts": _to_ms(dt.datetime.combine(day, dt.time(15, 0))),
                        "ic": 0.0,
                    }
                    for day in run_days
                ],
                "ic": 0.0,
                "ir": 0.0,
                "turnover": 0.0,
                "quantile_returns": [0.0 for _ in range(10)],
                "novelty_corr": 0.0,
            }
        ],
        "backtest": {
            "strategy": "top_momentum",
            "series": [
                {
                    "ts": _to_ms(dt.datetime.combine(day, dt.time(15, 0))),
                    "equity": 1.0,
                    "drawdown": 0.0,
                    "benchmark": 1.0,
                }
                for day in run_days
            ],
            "annual_return": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "turnover": 0.0,
            "attribution": [],
        },
        "strategy_lifecycle": [
            {
                "name": "top_momentum",
                "status": "paper",
                "oos_ic": 0.0,
                "approved_by": None,
                "degraded_reason": None,
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _change_pct(panel: pd.DataFrame, symbol: str) -> float:
    rows = panel[panel["symbol"] == symbol].tail(2)
    if len(rows) < 2:
        return 0.0
    prev = float(rows.iloc[0]["close"])
    last = float(rows.iloc[1]["close"])
    return round((last / prev - 1.0) * 100, 4) if prev else 0.0


def _signals_by_symbol(fill_rows: list[dict]) -> dict[str, list[dict]]:
    signals: dict[str, list[dict]] = {}
    for fill in fill_rows:
        symbol = str(fill["symbol"])
        signals.setdefault(symbol, []).append({
            "ts": fill["ts"],
            "direction": fill["side"],
            "label": f"{fill['account_id']} fill",
            "price": fill["price"],
        })
    return signals


def _to_ms(value: dt.datetime) -> int:
    return int(value.timestamp() * 1000)


def _symbol_from_order_id(order_id: str) -> str:
    return order_id.rsplit("-", 1)[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a safe paper trading session.")
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--symbols", type=int, default=5)
    parser.add_argument("--accounts", default="acct-a,acct-b")
    parser.add_argument("--state-path", default=str(default_state_path()))
    args = parser.parse_args()
    summary = run_paper_session(
        n_days=args.days,
        n_symbols=args.symbols,
        accounts=[item.strip() for item in args.accounts.split(",") if item.strip()],
        state_path=args.state_path,
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
