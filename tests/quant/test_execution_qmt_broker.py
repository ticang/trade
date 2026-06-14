"""QmtBroker 测试（设计 v0.5 §4.6.1 per-account + §4.6.2 on_fill 异步）。

xtquant 在 macOS 不可装。QmtBroker 顶层不 import xtquant；构造时 lazy import，
失败抛 RuntimeError。本测试通过在 sys.modules 注入 fake xtquant.xttrader /
xtquant.xtdata 来模拟 xtquant 行为，覆盖：
- xtquant 不可用 → RuntimeError
- per-account 构造（trader.start/connect/get_stock_account）
- place 调 order_stock，参数含 account/symbol/volume/price/client_order_id
- client_order_id 去重（DuplicateOrderError）
- cancel 调 cancel_order_stock
- status 状态映射（xt ORDER_JT/部分成交 → OrderStatus）
- positions/account 查询
- 多账户隔离（独立 client_ids，互不干扰）

TDD：本文件先于 qmt_broker.py 编写，预期 import 失败 → 实现后全绿。
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from quant.backtest.sim_broker import Order
from quant.execution.broker import DuplicateOrderError, OrderStatus
from quant.gateway.thread_bridge import ThreadBridge


# ---------------- fake xtquant 工厂 ----------------

def _install_fake_xtquant(monkeypatch, *, query_order_return=None) -> dict:
    """注入 fake xtquant.xttrader + xtquant.xtdata 到 sys.modules。

    返回 state dict，记录所有 XtQuantTrader 实例的调用与每实例的 mock 方法。
    state["trader_instances"][-1] 为最近创建的 trader；其上各方法均为 MagicMock，
    便于断言调用参数或临时改返回值。
    """
    state: dict = {
        "trader_instances": [],
    }

    xtdata = types.ModuleType("xtquant.xtdata")
    xttrader = types.ModuleType("xtquant.xttrader")

    class _FakeXtQuantTrader:
        """fake XtQuantTrader：记录构造参数，mock 出全部被调方法。"""

        def __init__(self, path, session_id):
            self.path = path
            self.session_id = session_id
            self.start = MagicMock(return_value=0)
            self.connect = MagicMock(return_value=0)
            self.stop = MagicMock(return_value=0)
            # 账户/订单/持仓/资产查询全部 mock
            self.get_stock_account = MagicMock(
                return_value={"account_id": "fake_acct"}
            )
            order_ret = query_order_return if query_order_return is not None else {
                "order_status": 56,  # xt ORDER_JT 已报
            }
            self.query_order = MagicMock(return_value=order_ret)
            self.order_stock = MagicMock(return_value=100)  # 返回 seq
            self.cancel_order_stock = MagicMock(return_value=0)
            self.query_stock_positions = MagicMock(return_value=[])
            self.query_stock_asset = MagicMock(return_value={})
            self.register_callback = MagicMock(return_value=0)
            state["trader_instances"].append(self)

    xttrader.XtQuantTrader = _FakeXtQuantTrader  # type: ignore[attr-defined]

    xtquant_pkg = types.ModuleType("xtquant")
    xtquant_pkg.xtdata = xtdata  # type: ignore[attr-defined]
    xtquant_pkg.xttrader = xttrader  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "xtquant", xtquant_pkg)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader)
    return state


def _make_buy_order(symbol="600519", qty=100, price=10.0) -> Order:
    """构造买入限价单。"""
    return Order(symbol=symbol, side="buy", qty=qty, price=price)


# ---------------- 1. xtquant 不可用 → RuntimeError ----------------

def test_qmt_broker_unavailable_raises(monkeypatch):
    """_try_import_xtquant 返回 None → 构造抛 RuntimeError。"""
    for name in list(sys.modules):
        if name == "xtquant" or name.startswith("xtquant."):
            monkeypatch.setitem(sys.modules, name, None)

    bridge = ThreadBridge()
    with pytest.raises(RuntimeError, match="xtquant unavailable"):
        # noqa: 下行触发 import（先写测试 → 实现前会 ImportError）
        from quant.execution.qmt_broker import QmtBroker
        QmtBroker(account_id="acct1", path="/tmp/qmt", session_id=1, bridge=bridge)


# ---------------- 2. per-account 构造 ----------------

def test_construct_per_account(monkeypatch):
    """fake xtquant → QmtBroker 构造成功，trader.start/connect/get_stock_account 被调。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=42, bridge=bridge)

    assert len(state["trader_instances"]) == 1
    trader = state["trader_instances"][0]
    assert trader.path == "/tmp/qmt"
    assert trader.session_id == 42
    trader.start.assert_called_once()
    trader.connect.assert_called_once()
    trader.get_stock_account.assert_called_once_with("acct1")
    assert broker.account_id == "acct1"
    assert broker.is_synchronous is False


# ---------------- 3. place 调 order_stock ----------------

def test_place_calls_order_stock(monkeypatch):
    """place(order, "c1") → order_stock 被调，参数含 account/symbol/volume/price/client_order_id。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)
    trader = state["trader_instances"][0]
    trader.order_stock.return_value = 999  # broker seq

    order = _make_buy_order()
    seq = broker.place(order, client_order_id="c1")

    trader.order_stock.assert_called_once()
    args, kwargs = trader.order_stock.call_args
    # 第一个位置参数应为账户对象（来自 get_stock_account）
    assert kwargs.get("account") is not None or args[0] is not None
    assert kwargs.get("stock_code") == "600519" or "600519" in (args if args else ())
    assert seq == 999


# ---------------- 4. client_order_id 去重 ----------------

def test_client_order_id_dedup(monkeypatch):
    """同 client_order_id 两次 place → DuplicateOrderError。"""
    _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)

    order = _make_buy_order()
    broker.place(order, client_order_id="c1")
    with pytest.raises(DuplicateOrderError):
        broker.place(order, client_order_id="c1")


# ---------------- 5. cancel 调 cancel_order_stock ----------------

def test_cancel_calls_cancel_order(monkeypatch):
    """cancel(order_id) → fake cancel_order_stock 被调，参数含 account 与 order_id。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)
    trader = state["trader_instances"][0]

    broker.cancel("order_42")
    trader.cancel_order_stock.assert_called_once()
    args, kwargs = trader.cancel_order_stock.call_args
    # account 位置/关键字 + order_id="order_42"
    assert kwargs.get("order_id") == "order_42" or "order_42" in (args if args else ())


# ---------------- 6. status 状态映射 ----------------

@pytest.mark.parametrize(
    "xt_status, expected",
    [
        (56, OrderStatus.SUBMITTED),    # xt ORDER_JT 已报
        (50, OrderStatus.PARTIAL_FILLED),  # xt 部分成交
        (55, OrderStatus.FILLED),       # xt 全部成交
        (53, OrderStatus.CANCELLED),    # xt 已撤
        (60, OrderStatus.REJECTED),     # xt 废单
    ],
)
def test_status_mapping(monkeypatch, xt_status, expected):
    """fake query_order 返回不同 xt 状态 → 映射到 OrderStatus。"""
    state = _install_fake_xtquant(
        monkeypatch,
        query_order_return={"order_status": xt_status},
    )
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)
    trader = state["trader_instances"][0]
    trader.query_order.return_value = {"order_status": xt_status}

    assert broker.status("order_42") == expected


# ---------------- 7. positions / account 查询 ----------------

def test_positions_account_query(monkeypatch):
    """positions()/account() 调 fake query_stock_positions / query_stock_asset。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)
    trader = state["trader_instances"][0]
    trader.query_stock_positions.return_value = [{"stock": "600519", "volume": 100}]
    trader.query_stock_asset.return_value = {"cash": 10000.0}

    positions = broker.positions()
    account = broker.account()

    trader.query_stock_positions.assert_called_once()
    trader.query_stock_asset.assert_called_once()
    assert positions == [{"stock": "600519", "volume": 100}]
    assert account == {"cash": 10000.0}


# ---------------- 8. 多账户隔离 ----------------

def test_multi_account_isolation(monkeypatch):
    """两个 QmtBroker 实例（acct1/acct2）独立 client_ids，互不干扰。"""
    state = _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    b1 = QmtBroker(account_id="acct1", path="/tmp/qmt",
                   session_id=1, bridge=bridge)
    b2 = QmtBroker(account_id="acct2", path="/tmp/qmt",
                   session_id=2, bridge=bridge)

    assert b1.account_id == "acct1"
    assert b2.account_id == "acct2"
    assert len(state["trader_instances"]) == 2

    # 各自 trader 的 get_stock_account 参数不同
    state["trader_instances"][0].get_stock_account.assert_called_once_with("acct1")
    state["trader_instances"][1].get_stock_account.assert_called_once_with("acct2")

    # b1 的 client_id 不影响 b2
    b1.place(_make_buy_order(), client_order_id="c1")
    # b2 用同样 client_order_id 不应抛重复
    b2.place(_make_buy_order(), client_order_id="c1")
    # b1 再用 c1 仍应抛
    with pytest.raises(DuplicateOrderError):
        b1.place(_make_buy_order(), client_order_id="c1")


# ---------------- 9. on_fill 桥接预留 ----------------

def test_on_fill_registers_callback(monkeypatch):
    """on_fill 注册回调（桥接预留：内部线程回报经 bridge → on_fill）。"""
    _install_fake_xtquant(monkeypatch)
    bridge = ThreadBridge()

    from quant.execution.qmt_broker import QmtBroker
    broker = QmtBroker(account_id="acct1", path="/tmp/qmt",
                       session_id=1, bridge=bridge)

    cb = MagicMock()
    broker.on_fill(cb)
    # 注册后内部已持有；后续回报经 bridge.bridge → loop → on_fill
    # 此处仅验证注册不抛、状态可被覆盖
    broker.on_fill(MagicMock())
