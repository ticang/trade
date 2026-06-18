"""基于快照 DataFrame 的备用行情网关。

该网关用于接入延迟行情、缓存行情或第三方批量拉取结果。它不伪装成实时
push 源：health 对分钟/tick 返回 DEGRADED，对日线历史返回 PASS。
"""
from datetime import datetime
from typing import Callable

import pandas as pd

from quant.events import BarEvent
from quant.gateway.base import GatewayHealth

__all__ = ["SnapshotMarketDataGateway"]


class SnapshotMarketDataGateway:
    """从标准 DataFrame 提供 history/bar_at/一次性 subscribe。

    输入 DataFrame 至少包含：symbol, freq, ts, close, volume, available_at。
    """

    _REQUIRED_COLUMNS = {"symbol", "freq", "ts", "close", "volume", "available_at"}

    def __init__(self, bars: pd.DataFrame, *, source: str = "snapshot") -> None:
        missing = self._REQUIRED_COLUMNS - set(bars.columns)
        if missing:
            raise ValueError(f"snapshot bars missing columns: {sorted(missing)}")
        self._source = source
        self._bars = bars.copy()
        self._bars["ts"] = pd.to_datetime(self._bars["ts"])
        self._bars["available_at"] = pd.to_datetime(self._bars["available_at"])
        self._bars = self._bars.sort_values(["symbol", "freq", "ts"]).reset_index(drop=True)

    def health(self, symbols: list[str], freq: str) -> GatewayHealth:
        checked_at = datetime.now()
        df = self._filter(symbols, freq)
        if len(df) == 0:
            return GatewayHealth(
                status="BLOCKED",
                source=self._source,
                quality="UNAVAILABLE",
                reason="snapshot has no rows for requested symbols/freq",
                checked_at=checked_at,
            )
        if freq == "1d":
            return GatewayHealth(
                status="PASS",
                source=self._source,
                quality="HISTORICAL",
                reason="snapshot daily rows are available",
                checked_at=checked_at,
            )
        return GatewayHealth(
            status="DEGRADED",
            source=self._source,
            quality="DELAYED",
            reason="snapshot rows are delayed, not realtime",
            checked_at=checked_at,
        )

    def subscribe(
        self,
        symbols: list[str],
        freq: str,
        on_bar: Callable[[BarEvent], None],
    ) -> None:
        """Emit the latest available row once for each symbol.

        This preserves the subscribe contract for shadow/simulation pipelines while
        making it clear through health() that the data is delayed.
        """
        df = self._filter(symbols, freq)
        if len(df) == 0:
            return
        for _, row in df.sort_values("ts").groupby("symbol", as_index=False).tail(1).iterrows():
            on_bar(_row_to_event(row))

    def history(
        self,
        symbol: str,
        freq: str,
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        df = self._bars[
            (self._bars["symbol"] == symbol)
            & (self._bars["freq"] == freq)
            & (self._bars["ts"] >= pd.Timestamp(start))
            & (self._bars["ts"] <= pd.Timestamp(end))
        ]
        if as_of is not None:
            df = df[df["available_at"] <= pd.Timestamp(as_of)]
        return df.copy().reset_index(drop=True)

    def bar_at(
        self,
        symbol: str,
        freq: str,
        t: datetime,
        decision_time: datetime,
    ) -> dict | None:
        df = self.history(symbol, freq, t, t, as_of=decision_time)
        if len(df) == 0:
            return None
        return df.iloc[-1].to_dict()

    def _filter(self, symbols: list[str], freq: str) -> pd.DataFrame:
        return self._bars[
            self._bars["symbol"].isin(symbols)
            & (self._bars["freq"] == freq)
        ]


def _row_to_event(row: pd.Series) -> BarEvent:
    return BarEvent(
        symbol=str(row["symbol"]),
        freq=str(row["freq"]),
        ts=pd.Timestamp(row["ts"]).to_pydatetime(),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )
