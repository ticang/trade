"""AkShare 日线快照行情源。

这是 QMT 实时行情不可用时的历史/盘后备用源。它不提供实时 tick，不用于
自动放行 live 策略；拉取结果会转换为 SnapshotMarketDataGateway 的标准列。
"""
from datetime import date, datetime
import time

import pandas as pd

from quant.gateway.snapshot import SnapshotMarketDataGateway

__all__ = ["AkShareDailySnapshotGateway"]


class AkShareDailySnapshotGateway(SnapshotMarketDataGateway):
    """AkShare daily OHLCV snapshot gateway."""

    @classmethod
    def fetch(
        cls,
        symbols: list[str],
        *,
        start: date,
        end: date,
        retries: int = 3,
        timeout: float = 10.0,
    ) -> "AkShareDailySnapshotGateway":
        import akshare as ak

        frames = [
            _fetch_one_symbol(
                ak,
                symbol,
                start=start,
                end=end,
                retries=retries,
                timeout=timeout,
            )
            for symbol in symbols
        ]
        bars = pd.concat(frames, ignore_index=True) if frames else _empty_bars()
        return cls(bars, source="akshare_daily")


def _fetch_one_symbol(
    ak,  # noqa: ANN001 - imported module or test stub
    symbol: str,
    *,
    start: date,
    end: date,
    retries: int,
    timeout: float,
) -> pd.DataFrame:
    ak_symbol = _to_akshare_symbol(symbol)
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            raw = ak.stock_zh_a_hist(
                symbol=ak_symbol,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
                timeout=timeout,
            )
            return _normalize_daily(symbol, raw)
        except Exception as exc:
            last_exc = exc
            if attempt == max(1, retries) - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("akshare retry loop exited unexpectedly") from last_exc


def _normalize_daily(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or len(raw) == 0:
        return _empty_bars()
    df = raw.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
    ).copy()
    required = ["trade_date", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"akshare daily missing columns: {missing}")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    out = pd.DataFrame({
        "symbol": symbol,
        "freq": "1d",
        "ts": df["trade_date"].dt.normalize() + pd.Timedelta(hours=15),
        "open": df["open"],
        "high": df["high"],
        "low": df["low"],
        "close": df["close"],
        "volume": df["volume"],
        "available_at": df["trade_date"].dt.normalize() + pd.Timedelta(hours=15),
    })
    return out.dropna(subset=["close"]).reset_index(drop=True)


def _to_akshare_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "symbol",
            "freq",
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "available_at",
        ]
    )
