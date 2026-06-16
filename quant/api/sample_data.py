from __future__ import annotations

import math

from quant.providers.trading_rule import classify_symbol


def ensure_supported_symbol(symbol: str) -> None:
    market, board, product_type = classify_symbol(symbol)
    if (market, board, product_type) == ("UNSUPPORTED", "unsupported", "unsupported"):
        raise ValueError("symbol outside current main-board scope")


def markets() -> list[dict]:
    rows = [
        {"symbol": "000001", "name": "平安银行", "last": 11.34, "change": 0.89, "volume": 234_000_000},
        {"symbol": "600519", "name": "贵州茅台", "last": 1685.5, "change": -1.23, "volume": 1_200_000_000},
        {"symbol": "002594", "name": "比亚迪", "last": 245.6, "change": -0.56, "volume": 567_000_000},
        {"symbol": "600036", "name": "招商银行", "last": 38.5, "change": 0.42, "volume": 412_000_000},
    ]
    return [r for r in rows if classify_symbol(r["symbol"])[1] == "main"]


def kline(symbol: str, n: int = 240) -> list[dict]:
    ensure_supported_symbol(symbol)
    start_price = 4100.0 if symbol == "600519" else 20.0
    price = start_price
    seed = 42
    bars: list[dict] = []
    day_start = 1_710_468_600_000

    def rnd() -> float:
        nonlocal seed
        seed = (seed * 9301 + 49297) % 233280
        return seed / 233280

    for i in range(n):
        open_price = price
        drift = (rnd() - 0.48) * 8
        close = max(start_price * 0.92, open_price + drift)
        high = max(open_price, close) + rnd() * 3
        low = min(open_price, close) - rnd() * 3
        volume = round(50_000 + rnd() * 200_000)
        bars.append(
            {
                "ts": day_start + i * 60_000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
        price = close
    return bars


def sentiment(symbol: str) -> list[dict]:
    bars = kline(symbol)
    seed = 7

    def rnd() -> float:
        nonlocal seed
        seed = (seed * 9301 + 49297) % 233280
        return seed / 233280

    return [{"ts": b["ts"], "score": (rnd() - 0.5) * 1.6} for b in bars]


def account() -> list[dict]:
    return [
        {"account_id": "acct1", "cash": 120000, "market_value": 280060, "total": 400060, "available": 118500},
        {"account_id": "acct2", "cash": 85000, "market_value": 49120, "total": 134120, "available": 82000},
    ]


def positions() -> list[dict]:
    return [
        {
            "account_id": "acct1",
            "symbol": "600519",
            "name": "贵州茅台",
            "qty": 100,
            "avg_cost": 1650,
            "last": 1685.5,
            "market_value": 168550,
            "pnl": 3550,
            "pnl_pct": 2.15,
            "weight": 0.32,
        },
        {
            "account_id": "acct1",
            "symbol": "000001",
            "name": "平安银行",
            "qty": 5000,
            "avg_cost": 11.5,
            "last": 11.34,
            "market_value": 56700,
            "pnl": -800,
            "pnl_pct": -1.39,
            "weight": 0.11,
        },
        {
            "account_id": "acct2",
            "symbol": "002594",
            "name": "比亚迪",
            "qty": 200,
            "avg_cost": 250,
            "last": 245.6,
            "market_value": 49120,
            "pnl": -880,
            "pnl_pct": -1.76,
            "weight": 0.09,
        },
    ]


def orders() -> list[dict]:
    return [
        {"order_id": "ord-1001", "account_id": "acct1", "symbol": "600519", "side": "buy", "price": 1680, "qty": 100, "filled_qty": 100, "status": "filled", "ts": 1718300000000},
        {"order_id": "ord-1002", "account_id": "acct1", "symbol": "000001", "side": "sell", "price": 11.6, "qty": 1000, "filled_qty": 0, "status": "pending", "ts": 1718310800000},
        {"order_id": "ord-1003", "account_id": "acct2", "symbol": "002594", "side": "buy", "price": 245, "qty": 300, "filled_qty": 0, "status": "submitted", "ts": 1718307200000},
    ]


def fills() -> list[dict]:
    return [
        {"fill_id": "fill-2001", "order_id": "ord-1001", "symbol": "600519", "side": "buy", "price": 1679.5, "qty": 100, "ts": 1718300100000},
        {"fill_id": "fill-2002", "order_id": "ord-1002", "symbol": "000001", "side": "sell", "price": 11.58, "qty": 500, "ts": 1718303700000},
    ]


def risk() -> dict:
    return {
        "total_position_pct": 0.62,
        "max_single_pct": 0.32,
        "industry_exposure": [
            {"industry": "白酒", "pct": 0.32},
            {"industry": "汽车", "pct": 0.09},
            {"industry": "银行", "pct": 0.11},
        ],
        "drawdown": -0.08,
        "drawdown_limit": -0.15,
        "circuit_breaker": "normal",
    }


def alerts() -> list[dict]:
    now = 1_718_320_000_000
    return [
        {"ts": now - 3_600_000, "level": "warn", "title": "事件驱动策略回撤接近阈值", "detail": "drawdown -18% vs limit -20%"},
        {"ts": now - 7_200_000, "level": "info", "title": "动量轮动调仓完成", "detail": "买入 600519, 卖出 000001"},
    ]


def strategies() -> list[dict]:
    return [
        {"name": "动量轮动", "status": "live", "account_id": "acct1", "ic": 0.062, "turnover": 0.45, "drawdown": -0.08, "allocation": 0.5},
        {"name": "情绪反向", "status": "paper", "account_id": "acct1", "ic": 0.038, "turnover": 0.62, "drawdown": -0.12, "allocation": 0.3},
        {"name": "事件驱动", "status": "degraded", "account_id": "acct2", "ic": 0.015, "turnover": 0.88, "drawdown": -0.18, "allocation": 0.2},
    ]


def factor_eval() -> list[dict]:
    ts = [
        1716422400,
        1716681600,
        1716768000,
        1716854400,
        1716940800,
        1717200000,
        1717286400,
        1717372800,
        1717459200,
        1717545600,
        1717804800,
        1717891200,
    ]
    return [
        {
            "name": "price_reversal_5d",
            "ic_series": [{"ts": t, "ic": [0.062, 0.048, 0.071, 0.053][i % 4]} for i, t in enumerate(ts)],
            "ic": 0.068,
            "ir": 0.74,
            "turnover": 0.42,
            "quantile_returns": [-0.18, -0.13, -0.08, -0.04, -0.01, 0.02, 0.05, 0.09, 0.13, 0.18],
            "novelty_corr": 0.31,
        }
    ]


def backtest() -> dict:
    points = []
    start = 1716422400
    equity = 1.0
    peak = 1.0
    benchmark = 1.0
    for i in range(90):
        noise = math.sin(i * 0.7) * 0.004 + math.cos(i * 1.3) * 0.003
        drift = 0.0016 + noise
        if 30 <= i <= 42:
            drift -= 0.006
        equity *= 1 + drift
        peak = max(peak, equity)
        benchmark *= 1 + 0.0006 + noise * 0.4
        points.append(
            {
                "ts": start + i * 86400,
                "equity": round(equity, 5),
                "drawdown": round(equity / peak - 1, 5),
                "benchmark": round(benchmark, 5),
            }
        )
    return {
        "strategy": "multi_factor_alpha_v3",
        "series": points,
        "annual_return": 0.312,
        "sharpe": 1.84,
        "max_drawdown": -0.094,
        "win_rate": 0.56,
        "turnover": 0.38,
        "attribution": [
            {"factor": "price_reversal_5d", "contribution": 0.072},
            {"factor": "earnings_surprise", "contribution": 0.118},
            {"factor": "liquidity_amihud", "contribution": -0.024},
        ],
    }


def strategy_lifecycle() -> list[dict]:
    return [
        {"name": "multi_factor_alpha_v3", "status": "live", "oos_ic": 0.094, "approved_by": "wk", "degraded_reason": None},
        {"name": "earnings_surprise_v2", "status": "paper", "oos_ic": 0.101, "approved_by": None, "degraded_reason": None},
        {"name": "intraday_reversal", "status": "degraded", "oos_ic": 0.038, "approved_by": "wk", "degraded_reason": "OOS IC dropped below 0.05 threshold for 5 sessions"},
    ]
