"""QMT 行情网关（§4.1.1 + xtquant lazy import / Windows-only）。

xtquant 仅在 Windows + QMT 终端环境下可装；macOS/Linux 无该包。
本模块顶层禁止 import xtquant——构造时 lazy import，失败抛 RuntimeError。
xtquant 内部线程回调经 ThreadBridge 桥接到 asyncio loop（§3.1 数据流）。
"""
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any, Iterable

import pandas as pd

from quant.gateway.base import GatewayHealth
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

    def __init__(
        self,
        path: str,
        session_id: int,
        bridge: ThreadBridge,
        *,
        poll_interval: float = 1.0,
        start_polling: bool = True,
    ) -> None:
        mods = _try_import_xtquant()
        if mods is None:
            raise RuntimeError(
                "xtquant unavailable (Windows-only): install QMT terminal on Windows"
            )
        self._xtdata, self._xttrader = mods
        self._bridge = bridge
        self._path = path
        self._data_dir = _qmt_data_dir(path)
        self._session_id = session_id
        self._trader = self._xttrader.XtQuantTrader(path, session_id)
        self._trader.start()
        self._trader.connect()
        # 已订阅 (symbol, freq) 集合，防重复订阅
        self._subscribed: set[tuple[str, str]] = set()
        self._run_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._subscription_ids: dict[tuple[str, str], int] = {}
        self._poll_interval = poll_interval
        self._start_polling = start_polling
        self._last_polled_ts: dict[tuple[str, str], datetime] = {}

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
            for bar in self._bars_from_xt_callback(data, symbols, freq):
                self._bridge.bridge(bar)

        self._ensure_xtdata_run_loop()
        if freq == "tick" and hasattr(self._xtdata, "subscribe_whole_quote"):
            pending = [s for s in symbols if (s, freq) not in self._subscribed]
            if pending:
                seq = self._xtdata.subscribe_whole_quote(pending, _on_xt_callback)
                for s in pending:
                    self._subscription_ids[(s, freq)] = seq
                    self._subscribed.add((s, freq))
                self._ensure_poll_loop()
            return

        for s in symbols:
            if (s, freq) in self._subscribed:
                continue
            seq = self._xtdata.subscribe_quote(
                s, period=period, callback=_on_xt_callback
            )
            self._subscription_ids[(s, freq)] = seq
            self._subscribed.add((s, freq))
        self._ensure_poll_loop()

    def _ensure_xtdata_run_loop(self) -> None:
        """Start xtdata.run() once so subscribe callbacks can be dispatched."""
        if self._run_thread is not None:
            return
        run = getattr(self._xtdata, "run", None)
        if not callable(run):
            return

        def _run() -> None:
            try:
                run()
            except Exception:
                # Connection loss is handled by higher-level gateway supervision.
                return

        self._run_thread = threading.Thread(
            target=_run,
            name="qmt-xtdata-run",
            daemon=True,
        )
        self._run_thread.start()

    def _ensure_poll_loop(self) -> None:
        """Start read-only polling fallback for terminals that do not push callbacks."""
        if not self._start_polling or self._poll_thread is not None:
            return
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="qmt-poll-fallback",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            interval = self._poll_interval if self._poll_interval > 0 else 1.0
            self._stop_event.wait(interval)

    def poll_once(self) -> None:
        """Poll subscribed symbols once and bridge fresh bars.

        This is a fallback for QMT terminals where subscribe APIs register
        successfully but no Python callback is pushed.
        """
        subscriptions = list(self._subscribed)
        if not subscriptions:
            return
        tick_symbols = sorted({s for s, freq in subscriptions if freq == "tick"})
        if tick_symbols:
            for bar in self._poll_full_tick(tick_symbols):
                self._bridge_polled_bar(bar)
        for symbol, freq in subscriptions:
            if freq != "tick":
                for bar in self._poll_market_data(symbol, freq):
                    self._bridge_polled_bar(bar)
        missing_tick = [
            s for s in tick_symbols
            if (s, "tick") not in self._last_polled_ts
        ]
        for symbol in missing_tick:
            for bar in self._poll_market_data(symbol, "tick"):
                self._bridge_polled_bar(bar)

    def health(self, symbols: list[str], freq: str) -> GatewayHealth:
        """Return QMT market-data health for the requested symbols/freq.

        QMT subscribe APIs may return a task id even when MiniQuote never pushes
        data. Treat a nonempty tick snapshot as realtime PASS, a nonempty recent
        minute bar as DEGRADED, and empty data as BLOCKED.
        """
        checked_at = datetime.now()
        if not symbols:
            return GatewayHealth(
                status="BLOCKED",
                source="qmt",
                quality="UNAVAILABLE",
                reason="no symbols requested",
                checked_at=checked_at,
            )

        if freq == "tick":
            tick_data = self._read_full_tick(symbols)
            if tick_data:
                return GatewayHealth(
                    status="PASS",
                    source="qmt",
                    quality="REALTIME",
                    reason="get_full_tick returned data",
                    checked_at=checked_at,
                )
            if any(self._has_recent_market_data(symbol, "tick") for symbol in symbols):
                return GatewayHealth(
                    status="DEGRADED",
                    source="qmt",
                    quality="DELAYED",
                    reason="full tick empty; recent 1m bar is available",
                    checked_at=checked_at,
                )
            return GatewayHealth(
                status="BLOCKED",
                source="qmt",
                quality="UNAVAILABLE",
                reason="full tick and recent 1m bar are empty",
                checked_at=checked_at,
            )

        if any(self._has_recent_market_data(symbol, freq) for symbol in symbols):
            return GatewayHealth(
                status="PASS",
                source="qmt",
                quality="HISTORICAL" if freq == "1d" else "DELAYED",
                reason="recent market_data_ex bar is available",
                checked_at=checked_at,
            )
        return GatewayHealth(
            status="BLOCKED",
            source="qmt",
            quality="UNAVAILABLE",
            reason="market_data_ex returned no recent rows",
            checked_at=checked_at,
        )

    def _poll_full_tick(self, symbols: list[str]) -> Iterable[dict]:
        data = self._read_full_tick(symbols)
        return self._bars_from_xt_callback(data, symbols, "tick")

    def _read_full_tick(self, symbols: list[str]) -> dict:
        get_full_tick = getattr(self._xtdata, "get_full_tick", None)
        if not callable(get_full_tick):
            return {}
        try:
            data = get_full_tick(symbols) or {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _poll_market_data(self, symbol: str, freq: str) -> Iterable[dict]:
        period = "1m" if freq == "tick" else _FREQ_TO_PERIOD.get(freq, freq)
        try:
            data = self._xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume", "amount"],
                stock_list=[symbol],
                period=period,
                count=1,
                dividend_type="none",
                fill_data=True,
                data_dir=self._data_dir,
            )
        except Exception:
            return []
        df = _extract_symbol_frame(data, symbol)
        if df is None or len(df) == 0:
            return []
        row = df.iloc[-1].to_dict()
        row.setdefault("stock", symbol)
        return self._bars_from_xt_callback(row, [symbol], freq)

    def _has_recent_market_data(self, symbol: str, freq: str) -> bool:
        period = "1m" if freq == "tick" else _FREQ_TO_PERIOD.get(freq, freq)
        try:
            data = self._xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume", "amount"],
                stock_list=[symbol],
                period=period,
                count=1,
                dividend_type="none",
                fill_data=True,
                data_dir=self._data_dir,
            )
        except Exception:
            return False
        df = _extract_symbol_frame(data, symbol)
        return df is not None and len(df) > 0

    def _bridge_polled_bar(self, bar: dict) -> None:
        key = (str(bar["symbol"]), str(bar["freq"]))
        ts = bar.get("ts")
        if not isinstance(ts, datetime):
            return
        last_ts = self._last_polled_ts.get(key)
        if last_ts is not None and ts <= last_ts:
            return
        self._last_polled_ts[key] = ts
        self._bridge.bridge(bar)

    @classmethod
    def _bars_from_xt_callback(
        cls,
        data: dict,
        symbols: list[str],
        freq: str,
    ) -> Iterable[dict]:
        """Normalize xtdata callback shapes into bar dictionaries."""
        if not isinstance(data, dict):
            return []
        if cls._looks_like_single_tick(data):
            bar = cls._build_bar_from_xtdata(data, symbols, freq)
            return [bar] if bar is not None else []

        bars: list[dict] = []
        for symbol, items in data.items():
            if isinstance(items, dict):
                iterable: Iterable[Any] = [items]
            elif isinstance(items, list):
                iterable = items
            else:
                continue
            for item in iterable:
                if not isinstance(item, dict):
                    continue
                payload = dict(item)
                payload.setdefault("stock", symbol)
                bar = cls._build_bar_from_xtdata(payload, symbols, freq)
                if bar is not None:
                    bars.append(bar)
        return bars

    @staticmethod
    def _looks_like_single_tick(data: dict) -> bool:
        return "time" in data and (
            "stock" in data
            or "close" in data
            or "lastPrice" in data
            or "last_price" in data
        )

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
        symbol = (
            data.get("stock")
            or data.get("stock_code")
            or (symbols[0] if symbols else "")
        )
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
            "close": float(
                data.get("close", data.get("lastPrice", data.get("last_price", 0.0)))
            ),
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
            data_dir=self._data_dir,
        )
        df = _extract_symbol_frame(df, symbol)
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
        for seq in self._subscription_ids.values():
            try:
                self._xtdata.unsubscribe_quote(seq)
            except (AttributeError, TypeError, ValueError):
                pass
        self._subscription_ids.clear()
        self._stop_event.set()
        try:
            self._trader.stop()  # type: ignore[attr-defined]
        except AttributeError:
            # fake/旧版 xttrader 无 stop，忽略
            pass


def _extract_symbol_frame(data: object, symbol: str) -> pd.DataFrame | None:
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, dict):
        value = data.get(symbol)
        if isinstance(value, pd.DataFrame):
            return value
    return None


def _qmt_data_dir(path: str) -> str | None:
    data_dir = Path(path) / "datadir"
    if data_dir.exists():
        return str(data_dir)
    return None
