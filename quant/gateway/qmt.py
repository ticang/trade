"""QMT 行情网关（§4.1.1 + xtquant lazy import / Windows-only）。

xtquant 仅在 Windows + QMT 终端环境下可装；macOS/Linux 无该包。
本模块顶层禁止 import xtquant——构造时 lazy import，失败抛 RuntimeError。
xtquant 内部线程回调经 ThreadBridge 桥接到 asyncio loop（§3.1 数据流）。
"""
from datetime import datetime, timezone

import pandas as pd

from quant.gateway.thread_bridge import ThreadBridge

__all__ = ["QmtGateway", "_try_import_xtquant"]


def _try_import_xtquant():
    """lazy import xtquant；不可用返回 None。

    顶层不 import xtquant，避免在 macOS/Linux 上 import 即崩。
    """
    try:
        import xtquant.xtdata as xtdata  # type: ignore[import-not-found]
        import xtquant.xttrader as xttrader  # type: ignore[import-not-found]
    except Exception:
        return None
    return xtdata, xttrader


# 频率 → xtquant 周期映射（xtdata period 取值）
_FREQ_TO_PERIOD = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "1d",
}


def _ms_to_datetime(ms: int) -> datetime:
    """xtdata 时间戳（毫秒）→ naive datetime（北京时间）。"""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _s_to_datetime(s: int) -> datetime:
    """xtdata 时间戳（秒）→ naive datetime。"""
    return datetime.fromtimestamp(s, tz=timezone.utc).replace(tzinfo=None)


class QmtGateway:
    """MarketDataGateway 的 QMT 实现。

    xtquant lazy import；macOS/无 xtquant 环境下构造即抛 RuntimeError。
    实盘订阅：xtdata.subscribe_quote 回调在 xtquant 内部线程，
    通过 ThreadBridge.bridge 桥接到 asyncio loop 上的 on_bar。
    """

    def __init__(self, path: str, session_id: int, bridge: ThreadBridge) -> None:
        mods = _try_import_xtquant()
        if mods is None:
            raise RuntimeError(
                "xtquant unavailable (Windows-only): install QMT terminal on Windows"
            )
        self._xtdata, self._xttrader = mods
        self._bridge = bridge
        self._path = path
        self._session_id = session_id
        self._trader = self._xttrader.XtQuantTrader(path, session_id)
        self._trader.start()
        self._trader.connect()
        # 已订阅 (symbol, freq) 集合，防重复订阅
        self._subscribed: set[tuple[str, str]] = set()

    # ---------------- 实时订阅 ----------------

    def subscribe(
        self,
        symbols: list[str],
        freq: str,
        on_bar,  # noqa: ANN001 — 与协议 Callable[[BarEvent], None] 对齐
    ) -> None:
        """订阅实时 bar。

        xtdata.subscribe_quote 的回调在 xtquant 内部线程触发；
        内部回调把 xtdata 的 data dict 转成 bar 字典（含 available_at），
        经 bridge.bridge 桥接到 asyncio loop 上的 on_bar。
        """
        period = _FREQ_TO_PERIOD.get(freq, freq)

        def _on_xt_callback(data: dict) -> None:
            # 内部线程上下文：构造 bar 后跨线程投递到 loop
            bar = self._build_bar_from_xtdata(data, symbols, freq)
            if bar is not None:
                self._bridge.bridge(bar)

        self._xtdata.subscribe_quote(
            symbols, period=period, callback=_on_xt_callback
        )
        for s in symbols:
            self._subscribed.add((s, freq))

    @staticmethod
    def _build_bar_from_xtdata(
        data: dict, symbols: list[str], freq: str
    ) -> dict | None:
        """从 xtdata 回调的 data dict 构造 bar 字典。

        xtdata 回调 data 通常包含 stock/time/open/high/low/close/volume/amount。
        available_at = bar 时间戳（保守取 bar ts，表示 bar 关闭后对外可见）。
        """
        if not isinstance(data, dict):
            return None
        symbol = data.get("stock") or (symbols[0] if symbols else "")
        ts_field = data.get("time")
        if ts_field is None:
            return None
        # xtdata 时间戳单位可能是秒或毫秒，按数量级自适应
        ts_val = int(ts_field)
        ts = _ms_to_datetime(ts_val) if ts_val > 10_000_000_000 else _s_to_datetime(ts_val)
        return {
            "symbol": symbol,
            "freq": freq,
            "ts": ts,
            "open": float(data.get("open", 0.0)),
            "high": float(data.get("high", 0.0)),
            "low": float(data.get("low", 0.0)),
            "close": float(data.get("close", 0.0)),
            "volume": float(data.get("volume", 0.0)),
            "amount": float(data.get("amount", 0.0)),
            "available_at": ts,
        }

    # ---------------- 历史查询 ----------------

    def history(
        self,
        symbol: str,
        freq: str,
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        """查询历史 bar。

        xtdata.get_market_data_ex 返回 DataFrame；本方法为其补 available_at 列
        （= bar ts），并按 as_of 做 PIT 过滤。
        """
        period = _FREQ_TO_PERIOD.get(freq, freq)
        start_str = start.strftime("%Y%m%d%H%M%S")
        end_str = end.strftime("%Y%m%d%H%M%S")
        df = self._xtdata.get_market_data_ex(
            stock_list=[symbol],
            period=period,
            start_time=start_str,
            end_time=end_str,
        )
        if df is None or len(df) == 0:
            return pd.DataFrame()
        df = df.copy()
        # xtdata DataFrame 索引/列格式不一，统一从 time 列或索引构造 ts/available_at
        if "time" in df.columns:
            ts_col = df["time"]
            # 自适应秒/毫秒
            if ts_col.iloc[0] > 10_000_000_000:
                df["ts"] = pd.to_datetime(ts_col.astype("int64"), unit="ms", utc=True).dt.tz_localize(None)
            else:
                df["ts"] = pd.to_datetime(ts_col.astype("int64"), unit="s", utc=True).dt.tz_localize(None)
        elif "ts" not in df.columns:
            # 无 time 列时回退用 index
            df["ts"] = pd.to_datetime(df.index, errors="coerce")
        df["available_at"] = df["ts"]
        df["symbol"] = symbol
        if as_of is not None:
            df = df[df["available_at"] <= as_of]
        return df.reset_index(drop=True)

    # ---------------- 单 bar 查询 ----------------

    def bar_at(
        self,
        symbol: str,
        freq: str,
        t: datetime,
        decision_time: datetime,
    ) -> dict | None:
        """返回 t 时刻的 bar；仅当 available_at <= decision_time 时返回，否则 None。"""
        # 扩大窗口覆盖 t 所在频率周期，再按 ts 精确匹配 + PIT 过滤
        df = self.history(symbol, freq, t, t.replace(hour=23, minute=59))
        if len(df) == 0:
            return None
        # 匹配 ts 与 t 同一天（日线）或同分钟（分钟线）
        match = df[df["ts"].dt.date == t.date()]
        if len(match) == 0:
            return None
        row = match.iloc[0]
        if row["available_at"] > decision_time:
            return None
        return row.to_dict()

    # ---------------- 生命周期 ----------------

    def close(self) -> None:
        """停止 trader，释放连接。"""
        try:
            self._trader.stop()  # type: ignore[attr-defined]
        except AttributeError:
            # fake/旧版 xttrader 无 stop，忽略
            pass
