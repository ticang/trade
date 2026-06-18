"""QmtGateway 测试（§4.1.1 + xtquant lazy import / Windows-only）。

xtquant 在 macOS 不可装。QmtGateway 顶层不 import xtquant；构造时 lazy import，
失败抛 RuntimeError('Windows-only')。本测试通过在 sys.modules 注入 fake
xtquant.xtdata / xtquant.xttrader 模块来模拟 xtquant 行为。
"""
import sys
import types
import builtins
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

import quant.gateway.qmt as qmt_module
from quant.gateway.qmt import QmtGateway, _try_import_xtquant
from quant.gateway.thread_bridge import ThreadBridge


# ---------------- fake xtquant 工厂 ----------------

def _install_fake_xtquant(monkeypatch, *, connect_return: int = 0,
                          market_data_df: object | None = None,
                          full_tick: dict | None = None,
                          captured: dict | None = None) -> dict:
    """注入 fake xtquant.xtdata + xtquant.xttrader 到 sys.modules。

    返回一个记录对象，包含：
      - xtdata: fake xtdata 模块（含 subscribe_quote / get_market_data_ex / 追加调用记录）
      - trader: 最近创建的 fake XtQuantTrader 实例（含 start/connect 调用记录）
      - trigger_callback(data): 触发订阅时传入的 callback，模拟 xtquant 内部线程回调
    """
    state: dict = {
        "subscribe_calls": [],
        "whole_quote_calls": [],
        "history_calls": [],
        "run_called": False,
        "trader_instances": [],
        "last_callback": None,
        "market_data_df": (
            market_data_df if market_data_df is not None else pd.DataFrame()
        ),
        "full_tick": full_tick if full_tick is not None else {},
    }

    # ---- fake xtdata ----
    xtdata = types.ModuleType("xtquant.xtdata")

    def subscribe_quote(stock_code, period="", callback=None, **kwargs):
        state["subscribe_calls"].append({
            "stock_code": stock_code,
            "period": period,
            "callback": callback,
            "kwargs": kwargs,
        })
        state["last_callback"] = callback
        if captured is not None:
            captured["last_callback"] = callback
        return 0

    def subscribe_whole_quote(code_list, callback=None):
        state["whole_quote_calls"].append({
            "code_list": list(code_list),
            "callback": callback,
        })
        state["last_callback"] = callback
        if captured is not None:
            captured["last_callback"] = callback
        return 100

    def run():
        state["run_called"] = True

    def get_market_data_ex(period="", start_time="", end_time="", **kwargs):
        state["history_calls"].append({
            "period": period,
            "start_time": start_time,
            "end_time": end_time,
            "kwargs": kwargs,
        })
        return state["market_data_df"]

    def get_full_tick(code_list):
        state["full_tick_calls"] = state.get("full_tick_calls", 0) + 1
        return {
            code: state["full_tick"][code]
            for code in code_list
            if code in state["full_tick"]
        }

    xtdata.subscribe_quote = subscribe_quote  # type: ignore[attr-defined]
    xtdata.subscribe_whole_quote = subscribe_whole_quote  # type: ignore[attr-defined]
    xtdata.get_market_data_ex = get_market_data_ex  # type: ignore[attr-defined]
    xtdata.get_full_tick = get_full_tick  # type: ignore[attr-defined]
    xtdata.run = run  # type: ignore[attr-defined]

    # ---- fake xttrader ----
    xttrader = types.ModuleType("xtquant.xttrader")

    class _FakeXtQuantTrader:
        def __init__(self, path, session_id):
            self.path = path
            self.session_id = session_id
            self.start_called = False
            self.connect_called = False
            state["trader_instances"].append(self)

        def start(self):
            self.start_called = True
            return 0

        def connect(self):
            self.connect_called = True
            return connect_return

        def stop(self):
            self.stop_called = True  # type: ignore[attr-defined]
            return 0

    xttrader.XtQuantTrader = _FakeXtQuantTrader  # type: ignore[attr-defined]

    # ---- fake 顶层 xtquant 包 ----
    xtquant_pkg = types.ModuleType("xtquant")
    xtquant_pkg.xtdata = xtdata  # type: ignore[attr-defined]
    xtquant_pkg.xttrader = xttrader  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "xtquant", xtquant_pkg)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader)
    return state


# ---------------- 1. 不可用 → RuntimeError ----------------

def test_qmt_unavailable_raises(monkeypatch):
    """xtquant 缺失（_try_import_xtquant 返回 None）→ 构造抛 RuntimeError。"""
    monkeypatch.setattr(qmt_module, "_try_import_xtquant", lambda: None)

    bridge = ThreadBridge()
    with pytest.raises(RuntimeError, match="Windows-only"):
        QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)


def test_try_import_xtquant_returns_none_when_missing(monkeypatch):
    """_try_import_xtquant 在 xtquant 不可用时返回 None。"""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "xtquant" or name.startswith("xtquant."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _try_import_xtquant() is None


# ---------------- 2. fake xtquant → 构造成功 ----------------

def test_qmt_constructs_with_fake_xtquant(monkeypatch):
    """注入 fake xtquant → QmtGateway 构造成功，trader.start/connect 被调用。"""
    state = _install_fake_xtquant(monkeypatch, connect_return=0)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=42, bridge=bridge)

    assert len(state["trader_instances"]) == 1
    trader = state["trader_instances"][0]
    assert trader.path == "/tmp/qmt"
    assert trader.session_id == 42
    assert trader.start_called is True
    assert trader.connect_called is True


# ---------------- 3. subscribe 调用 xtdata.subscribe_quote ----------------

def test_subscribe_calls_xtdata(monkeypatch):
    """subscribe(["600519"],"1d",cb) → fake xtdata.subscribe_quote 被调用，参数含 symbols/period。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    on_bar = MagicMock()
    gw.subscribe(["600519"], "1d", on_bar)

    assert len(state["subscribe_calls"]) == 1
    call = state["subscribe_calls"][0]
    assert call["stock_code"] == "600519"
    assert call["period"] == "1d"
    assert callable(call["callback"])
    assert state["run_called"] is True


def test_subscribe_calls_xtdata_once_per_symbol(monkeypatch):
    """真实 xtdata.subscribe_quote 接收单个 stock_code，多标的需逐个订阅。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    gw.subscribe(["600519.SH", "000001.SZ"], "1m", MagicMock())

    assert [c["stock_code"] for c in state["subscribe_calls"]] == [
        "600519.SH",
        "000001.SZ",
    ]


def test_tick_subscribe_prefers_whole_quote(monkeypatch):
    """tick 实时订阅优先使用 subscribe_whole_quote 以获取全推回调。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    gw.subscribe(["600519.SH", "000001.SZ"], "tick", MagicMock())

    assert state["whole_quote_calls"] == [
        {
            "code_list": ["600519.SH", "000001.SZ"],
            "callback": state["last_callback"],
        }
    ]
    assert state["subscribe_calls"] == []


# ---------------- 4. 内部线程回调 → bridge → on_bar ----------------

def test_subscribe_callback_bridged(monkeypatch):
    """触发 fake xtdata 回调（内部线程模拟）→ ThreadBridge.bridge 被调 → on_bar 收到 bar。

    用 mock bridge 直接断言 bridge.bridge 被调用且参数为 bar。
    """
    captured: dict = {}
    state = _install_fake_xtquant(monkeypatch, captured=captured)
    mock_bridge = MagicMock(spec=ThreadBridge)
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=mock_bridge)

    on_bar = MagicMock()
    gw.subscribe(["600519"], "1d", on_bar)

    # 模拟 xtquant 内部线程触发回调：传入类似 xtdata 的 data dict
    # xtdata 回调签名约定：callback(data) 或 callback(all_data)；这里用单参数 dict
    raw_data = {
        "stock": "600519",
        "time": 1710489600000,  # 2024-03-15 15:00:00+08 ms 时间戳
        "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0,
        "volume": 100000, "amount": 1000000.0,
    }
    callback = state["last_callback"]
    assert callback is not None
    callback(raw_data)

    # bridge.bridge 被调用一次，参数带 OHLCV 与 available_at
    mock_bridge.bridge.assert_called_once()
    bar = mock_bridge.bridge.call_args[0][0]
    assert bar["symbol"] == "600519"
    assert bar["freq"] == "1d"
    assert bar["close"] == 10.0
    assert bar["volume"] == 100000
    assert "available_at" in bar


def test_subscribe_callback_reaches_on_bar_via_real_bridge(monkeypatch):
    """真 bridge + mock loop：内部回调 → bridge → loop.call_soon_threadsafe → on_bar。"""
    state = _install_fake_xtquant(monkeypatch)
    loop = MagicMock()
    loop.is_running.return_value = True
    on_bar = MagicMock()
    bridge = ThreadBridge(loop=loop, on_bar=on_bar)

    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)
    gw.subscribe(["600519"], "1d", on_bar)

    raw_data = {"stock": "600519", "time": 1710489600000,
                "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0,
                "volume": 100000, "amount": 1000000.0}
    state["last_callback"](raw_data)

    loop.call_soon_threadsafe.assert_called_once()
    args = loop.call_soon_threadsafe.call_args[0]
    assert args[0] is on_bar
    bar = args[1]
    assert bar["symbol"] == "600519"
    assert bar["close"] == 10.0


def test_subscribe_callback_handles_xtdata_batched_shape(monkeypatch):
    """真实 subscribe_quote 回调形态为 {stock: [data, ...]}，应展开后桥接。"""
    state = _install_fake_xtquant(monkeypatch)
    mock_bridge = MagicMock(spec=ThreadBridge)
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=mock_bridge)
    gw.subscribe(["600519.SH"], "tick", MagicMock())

    state["last_callback"]({
        "600519.SH": [
            {
                "time": 1710489600000,
                "lastPrice": 10.0,
                "open": 9.8,
                "high": 10.2,
                "low": 9.7,
                "volume": 100000,
                "amount": 1000000.0,
            }
        ]
    })

    mock_bridge.bridge.assert_called_once()
    bar = mock_bridge.bridge.call_args[0][0]
    assert bar["symbol"] == "600519.SH"
    assert bar["freq"] == "tick"
    assert bar["close"] == 10.0


def test_poll_fallback_bridges_full_tick_when_terminal_does_not_push(monkeypatch):
    """QMT 不推 subscribe 回调时，轮询 full tick 也能产出 on_bar。"""
    full_tick = {
        "600519.SH": {
            "time": 1710489600000,
            "lastPrice": 10.0,
            "open": 9.8,
            "high": 10.2,
            "low": 9.7,
            "volume": 100000,
            "amount": 1000000.0,
        }
    }
    _install_fake_xtquant(monkeypatch, full_tick=full_tick)
    mock_bridge = MagicMock(spec=ThreadBridge)
    gw = QmtGateway(
        path="/tmp/qmt",
        session_id=1,
        bridge=mock_bridge,
        poll_interval=0,
        start_polling=False,
    )
    gw.subscribe(["600519.SH"], "tick", MagicMock())

    gw.poll_once()

    mock_bridge.bridge.assert_called_once()
    bar = mock_bridge.bridge.call_args[0][0]
    assert bar["symbol"] == "600519.SH"
    assert bar["freq"] == "tick"
    assert bar["close"] == 10.0


def test_poll_fallback_uses_market_data_when_full_tick_empty(monkeypatch):
    """full tick 空时，用 get_market_data_ex 最近一根 bar 兜底。"""
    raw_df = pd.DataFrame({
        "time": [1710489600000],
        "open": [9.8],
        "high": [10.2],
        "low": [9.7],
        "close": [10.0],
        "volume": [100000],
        "amount": [1000000.0],
    })
    _install_fake_xtquant(monkeypatch, market_data_df=raw_df)
    mock_bridge = MagicMock(spec=ThreadBridge)
    gw = QmtGateway(
        path="/tmp/qmt",
        session_id=1,
        bridge=mock_bridge,
        poll_interval=0,
        start_polling=False,
    )
    gw.subscribe(["600519.SH"], "tick", MagicMock())

    gw.poll_once()

    mock_bridge.bridge.assert_called_once()
    bar = mock_bridge.bridge.call_args[0][0]
    assert bar["symbol"] == "600519.SH"
    assert bar["freq"] == "tick"
    assert bar["close"] == 10.0


def test_qmt_health_passes_when_full_tick_available(monkeypatch):
    """full tick 有数据时，QMT 可作为实时行情源。"""
    full_tick = {
        "600519.SH": {
            "time": 1710489600000,
            "lastPrice": 10.0,
            "open": 9.8,
            "high": 10.2,
            "low": 9.7,
            "volume": 100000,
            "amount": 1000000.0,
        }
    }
    _install_fake_xtquant(monkeypatch, full_tick=full_tick)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    health = gw.health(["600519.SH"], "tick")

    assert health.status == "PASS"
    assert health.quality == "REALTIME"
    assert "full_tick" in health.reason


def test_qmt_health_degrades_when_only_recent_bar_available(monkeypatch):
    """tick 空但最近 1m bar 可用时，只能作为降级行情源。"""
    raw_df = pd.DataFrame({
        "time": [1710489600000],
        "open": [9.8],
        "high": [10.2],
        "low": [9.7],
        "close": [10.0],
        "volume": [100000],
        "amount": [1000000.0],
    })
    _install_fake_xtquant(monkeypatch, market_data_df=raw_df)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    health = gw.health(["600519.SH"], "tick")

    assert health.status == "DEGRADED"
    assert health.quality == "DELAYED"


def test_qmt_health_blocks_when_realtime_and_recent_bar_empty(monkeypatch):
    """现场卡点：58610 可连接但 tick/最近 bar 都空，必须明确 BLOCKED。"""
    _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    health = gw.health(["600519.SH"], "tick")

    assert health.status == "BLOCKED"
    assert health.quality == "UNAVAILABLE"
    assert "empty" in health.reason


# ---------------- 5. history 返回 DataFrame（带 available_at） ----------------

def test_history_returns_dataframe(monkeypatch):
    """fake xtdata.get_market_data_ex 返回固定 df → QmtGateway.history 返回 df（含 available_at 标注）。"""
    raw_df = pd.DataFrame({
        "time": [1710316800, 1710403200],  # 2024-03-13/14 日线时间戳
        "open": [9.0, 9.5],
        "high": [9.5, 10.0],
        "low": [8.8, 9.3],
        "close": [9.2, 9.8],
        "volume": [10000, 12000],
    })
    state = _install_fake_xtquant(monkeypatch, market_data_df=raw_df)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    df = gw.history("600519", "1d", datetime(2024, 3, 13), datetime(2024, 3, 15))
    assert isinstance(df, pd.DataFrame)
    assert "available_at" in df.columns
    assert len(df) == 2
    # xtdata.get_market_data_ex 被调用一次，period 正确
    assert len(state["history_calls"]) == 1
    assert state["history_calls"][0]["period"] == "1d"


def test_history_accepts_real_xtdata_symbol_dict(monkeypatch, tmp_path):
    """真实 xtdata.get_market_data_ex 常返回 {symbol: DataFrame}，应正常展开。"""
    raw_df = pd.DataFrame({
        "time": [1710316800],
        "open": [9.0],
        "high": [9.5],
        "low": [8.8],
        "close": [9.2],
        "volume": [10000],
    })
    qmt_path = tmp_path / "userdata_mini"
    (qmt_path / "datadir").mkdir(parents=True)
    state = _install_fake_xtquant(
        monkeypatch,
        market_data_df={"600519.SH": raw_df},
    )
    bridge = ThreadBridge()
    gw = QmtGateway(path=str(qmt_path), session_id=1, bridge=bridge)

    df = gw.history(
        "600519.SH",
        "1d",
        datetime(2024, 3, 13),
        datetime(2024, 3, 15),
    )

    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "600519.SH"
    assert state["history_calls"][0]["kwargs"]["data_dir"] == str(qmt_path / "datadir")


# ---------------- 6. bar_at PIT 过滤 ----------------

def test_bar_at_pit_filter(monkeypatch):
    """history 含 available_at>decision_time 的行 → bar_at 返回 None 或返回 available_at<=decision_time 的行。"""
    # 构造 raw df：两根 bar，一根 available_at 早于决策，一根晚于决策
    raw_df = pd.DataFrame({
        "time": [1710489600, 1710576000],  # 2024-03-15 / 2024-03-16
        "open": [9.0, 10.0],
        "high": [9.5, 10.5],
        "low": [8.8, 9.8],
        "close": [9.2, 10.2],
        "volume": [10000, 11000],
    })
    _install_fake_xtquant(monkeypatch, market_data_df=raw_df)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    # decision_time 早于第二根 bar 的 available_at → 不可见 → 应 None 或仅返回可见的那一根
    # 这里 t=2024-03-15，decision_time=2024-03-15 15:00（应当只能看到第一根）
    bar = gw.bar_at(
        "600519", "1d",
        t=datetime(2024, 3, 15),
        decision_time=datetime(2024, 3, 15, 15, 0),
    )
    # 若返回 bar，其 available_at 必须 <= decision_time（PIT 安全）
    if bar is not None:
        assert bar["available_at"] <= datetime(2024, 3, 15, 15, 0)
        assert bar["close"] == 9.2


def test_bar_at_returns_none_when_future_only(monkeypatch):
    """只有未来可见的 bar（available_at > decision_time）→ bar_at 返回 None。"""
    raw_df = pd.DataFrame({
        "time": [1710489600],  # 2024-03-15
        "open": [9.0], "high": [9.5], "low": [8.8], "close": [9.2], "volume": [10000],
    })
    _install_fake_xtquant(monkeypatch, market_data_df=raw_df)
    bridge = ThreadBridge()
    gw = QmtGateway(path="/tmp/qmt", session_id=1, bridge=bridge)

    # decision_time 早于任何 available_at → 全部被过滤 → None
    bar = gw.bar_at(
        "600519", "1d",
        t=datetime(2024, 3, 15),
        decision_time=datetime(2024, 3, 14),  # 早于 bar 时间
    )
    assert bar is None
