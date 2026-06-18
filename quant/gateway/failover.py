"""多源行情仲裁网关。

QMT 现场卡点表明：交易侧可用不等于 MiniQuote 实时行情可用。本模块把
行情源选择收敛到一个明确位置，避免策略层误把“订阅注册成功”当作
“实时数据可用”。
"""
from datetime import datetime
from typing import Callable, Iterable

import pandas as pd

from quant.gateway.base import BarEvent, GatewayHealth, MarketDataGateway

__all__ = ["FailoverMarketDataGateway", "MarketDataUnavailable"]


class MarketDataUnavailable(RuntimeError):
    """所有候选行情源均不可用。"""

    def __init__(self, message: str, health: list[GatewayHealth]) -> None:
        super().__init__(message)
        self.health = health


class FailoverMarketDataGateway:
    """按健康状态选择行情源的 MarketDataGateway 实现。

    选择规则：
    - 优先使用第一个 health.status == PASS 的源；
    - 没有 PASS 时允许使用 DEGRADED 源，但调用方可通过 health() 看到降级；
    - 全部 BLOCKED 时抛 MarketDataUnavailable，防止 silent success。
    """

    def __init__(self, gateways: Iterable[MarketDataGateway]) -> None:
        self._gateways = list(gateways)
        if not self._gateways:
            raise ValueError("at least one gateway is required")

    def health(self, symbols: list[str], freq: str) -> GatewayHealth:
        health = self._health_all(symbols, freq)
        for item in health:
            if item.status == "PASS":
                return item
        for item in health:
            if item.status == "DEGRADED":
                return item
        return health[0]

    def subscribe(
        self,
        symbols: list[str],
        freq: str,
        on_bar: Callable[[BarEvent], None],
    ) -> None:
        gateway, _ = self._select(symbols, freq)
        gateway.subscribe(symbols, freq, on_bar)

    def history(
        self,
        symbol: str,
        freq: str,
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        errors: list[GatewayHealth] = []
        for gateway in self._gateways:
            health = _gateway_health(gateway, [symbol], freq)
            errors.append(health)
            if health.status == "BLOCKED":
                continue
            df = gateway.history(symbol, freq, start, end, as_of=as_of)
            if df is not None and len(df) > 0:
                return df
        raise MarketDataUnavailable("no gateway returned history data", errors)

    def bar_at(
        self,
        symbol: str,
        freq: str,
        t: datetime,
        decision_time: datetime,
    ) -> object | None:
        for gateway in self._gateways:
            health = _gateway_health(gateway, [symbol], freq)
            if health.status == "BLOCKED":
                continue
            bar = gateway.bar_at(symbol, freq, t, decision_time)
            if bar is not None:
                return bar
        return None

    def _select(
        self,
        symbols: list[str],
        freq: str,
    ) -> tuple[MarketDataGateway, GatewayHealth]:
        health = self._health_all(symbols, freq)
        for gateway, item in zip(self._gateways, health):
            if item.status == "PASS":
                return gateway, item
        for gateway, item in zip(self._gateways, health):
            if item.status == "DEGRADED":
                return gateway, item
        raise MarketDataUnavailable("no live market data gateway available", health)

    def _health_all(self, symbols: list[str], freq: str) -> list[GatewayHealth]:
        return [_gateway_health(gateway, symbols, freq) for gateway in self._gateways]


def _gateway_health(
    gateway: MarketDataGateway,
    symbols: list[str],
    freq: str,
) -> GatewayHealth:
    health = getattr(gateway, "health", None)
    if callable(health):
        return health(symbols, freq)
    return GatewayHealth(
        status="PASS",
        source=type(gateway).__name__,
        quality="REALTIME",
        reason="gateway does not expose health(); assuming pass",
        checked_at=datetime.now(),
    )
