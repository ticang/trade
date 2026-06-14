"""M0 集成验收测试：逐条对应设计 §11 M0 量化验收标准。

本文件是 M0 的验收闸门，串联全部 M0 组件（store/repository/pit/provider/
quality/events），证明它们能协同工作。每个测试函数对应一条验收条：

  1. read_write        读写：SqliteStore + DuckdbStore 经 Repository 的 CRUD
  2. pit               PIT 断言：derive_available_at + pit_confidence_for + max_available_at
  3. rule_interval     规则按日取值：TradingRuleProvider 区间命中
  4. quality_gate      质量门禁拦截：脏 bar DENY / 干净 PASS / 未知 dataset DENY
  5. multi_account     多账户隔离：Position/Order 按 account_id 互不可见
  6. calendar_makeup   调休日历：补班日 is_trading_day True / 国庆 False
  7. event_bus         事件总线：publish BarEvent 订阅者收到，异常相互隔离

每个测试 self-contained：用 tmp_path 造临时库，finally 收尾关连接/停线程。
"""
from __future__ import annotations

import datetime as _dt

import pytest

from quant.data.duckdb_store import DuckdbStore
from quant.data.models import Account, Bar
from quant.data.pit import (
    derive_available_at,
    max_available_at,
    pit_confidence_for,
)
from quant.data.repository import (
    DuckdbBarRepository,
    SqliteAccountRepository,
    SqliteOrderRepository,
    SqlitePositionRepository,
)
from quant.data.sqlite_store import SqliteStore
from quant.events import BarEvent, EventBus
from quant.providers.calendar import TradingCalendar
from quant.providers.trading_rule import TradingRuleProvider
from quant.quality.gate import DataQualityGate, Verdict


# ---------------------------------------------------------------------------
# 共用构造辅助
# ---------------------------------------------------------------------------


# trading_rule 插入语句（列对齐 schema.SQLITE_DDL）
_INSERT_RULE = (
    "INSERT INTO trading_rule (rule_id, market, board, product_type, "
    "effective_from, effective_to, source_url, source_confidence, rule_json, "
    "reviewed_by, reviewed_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _insert_rule(
    store: SqliteStore,
    rule_id: str,
    market: str,
    board: str,
    product_type: str,
    effective_from: _dt.date,
    effective_to: _dt.date | None,
) -> None:
    """插一条 trading_rule 并 flush 落盘。"""
    store.execute(
        _INSERT_RULE,
        (
            rule_id, market, board, product_type,
            effective_from.isoformat(),
            effective_to.isoformat() if effective_to else None,
            "http://example/rule",
            "official",
            '{"price_tick": 0.01}',
            None, None,
        ),
    )
    assert store.flush(timeout=5.0)


def _bar(symbol: str, trade_date: str, close: float = 10.0) -> Bar:
    """构造一根日 K（17 列，对齐 Bar dataclass）。"""
    return Bar(
        symbol=symbol, freq="1d",
        trade_date=_dt.date.fromisoformat(trade_date), ts=0,
        open=close, high=close, low=close, close=close,
        volume=1000.0, amount=10000.0,
        adj_type="none", source="tushare",
        available_at=0, received_ts=0, ingested_at=0, as_of=0,
        pit_confidence="live",
    )


def _order(order_id: str, account_id: str, symbol: str = "600519.SH") -> dict:
    """构造一笔订单 dict（字段对齐 orders 表）。"""
    return {
        "order_id": order_id, "account_id": account_id,
        "strategy": "demo", "symbol": symbol, "side": "buy",
        "qty": 100.0, "price": 1800.0, "status": "new",
        "broker": "xtp", "client_order_id": f"c-{order_id}",
        "created_ts": 1700000000, "updated_ts": 1700000000,
    }


# ===========================================================================
# 验收条 1：读写（SqliteStore + DuckdbStore 经 Repository 的 CRUD）
# ===========================================================================


def test_acceptance_read_write(tmp_path):
    """§11-1 读写：SQLite 写账户读回；DuckDB append Bar 后区间查询。"""
    sqlite = SqliteStore(str(tmp_path / "acc.db"))
    sqlite.start()
    duckdb = DuckdbStore(str(tmp_path / "bar.duckdb"))
    try:
        # SQLite 经 Repository：账户写入 → get 取回，字段全等
        acct_repo = SqliteAccountRepository(sqlite)
        acct_repo.add(Account("acct-1", "xtp", "paper", "验收账户"))

        got = acct_repo.get("acct-1")
        assert got is not None
        assert (got.account_id, got.broker, got.env, got.name) == (
            "acct-1", "xtp", "paper", "验收账户",
        )

        # DuckDB 经 Repository：append 3 根 Bar → 区间查询按 trade_date 升序
        bar_repo = DuckdbBarRepository(duckdb)
        bar_repo.append([
            _bar("600519.SH", "2024-01-02", close=1810.0),
            _bar("600519.SH", "2024-01-01", close=1800.0),
            _bar("600519.SH", "2024-01-03", close=1820.0),
        ])
        rows = bar_repo.query(
            "600519.SH", _dt.date(2024, 1, 1), _dt.date(2024, 1, 3),
        )
        assert len(rows) == 3
        assert [r["trade_date"] for r in rows] == [
            _dt.date(2024, 1, 1), _dt.date(2024, 1, 2), _dt.date(2024, 1, 3),
        ]
        assert [r["close"] for r in rows] == [1800.0, 1810.0, 1820.0]
    finally:
        duckdb.close()
        sqlite.stop()


# ===========================================================================
# 验收条 2：PIT 断言
# ===========================================================================


def test_acceptance_pit():
    """§11-2 PIT 断言：
    - 实时段（live=True）pit_confidence_for='live'，时刻为 T 日 15:00
    - 回填段（live=False）pit_confidence_for='rule_inferred'
    - max_available_at 取依赖字段 available_at 的 max
    """
    td = _dt.date(2024, 6, 14)

    # 实时段
    live_at = derive_available_at("daily_ohlc", td, live=True)
    assert live_at == _dt.datetime(2024, 6, 14, 15, 0)
    assert pit_confidence_for(live=True) == "live"

    # 回填段：时刻相同（live 仅影响 confidence 标记，不影响时刻）
    backfill_at = derive_available_at("daily_ohlc", td, live=False)
    assert backfill_at == live_at
    assert pit_confidence_for(live=False) == "rule_inferred"

    # max_available_at：取依赖字段 available_at 的最大值
    deps = [
        _dt.datetime(2024, 6, 14, 15, 0),
        _dt.datetime(2024, 6, 14, 18, 0),  # longhubang 更晚披露
        _dt.datetime(2024, 6, 15, 0, 0),   # margin T+1 最晚
    ]
    assert max_available_at(deps) == _dt.datetime(2024, 6, 15, 0, 0)

    # 空依赖序列应抛 ValueError
    with pytest.raises(ValueError):
        max_available_at([])


# ===========================================================================
# 验收条 3：规则按日取值
# ===========================================================================


def test_acceptance_rule_interval(tmp_path):
    """§11-3 规则按日取值：插 fixture 规则（SSE main stock 2024-01-01~None），
    rules_for 命中区间内日期、未命中区间外日期。
    """
    sqlite = SqliteStore(str(tmp_path / "rule.db"))
    sqlite.start()
    try:
        _insert_rule(
            sqlite, "R-SSE-MAIN-2024",
            market="SSE", board="main", product_type="stock",
            effective_from=_dt.date(2024, 1, 1),
            effective_to=None,  # 永不过期
        )
        provider = TradingRuleProvider(sqlite)

        # 区间内：600519 → (SSE, main, stock) 命中
        hit = provider.rules_for("600519", _dt.date(2024, 6, 14))
        assert hit is not None
        assert hit.rule_id == "R-SSE-MAIN-2024"
        assert hit.market == "SSE"
        assert hit.effective_to is None

        # 区间外：2023-12-31 早于 effective_from，返回 None
        assert provider.rules_for("600519", _dt.date(2023, 12, 31)) is None

        # 不匹配的 symbol 分类（ETF → etp/fund）无规则，返回 None
        assert provider.rules_for("510300", _dt.date(2024, 6, 14)) is None
    finally:
        sqlite.stop()


# ===========================================================================
# 验收条 4：质量门禁拦截
# ===========================================================================


def test_acceptance_quality_gate():
    """§11-4 质量门禁拦截：
    - 干净 bar PASS
    - 脏 bar（OHLC 不一致 / 缺失）DENY
    - 未知 dataset DENY
    """
    gate = DataQualityGate()

    # 干净 bar
    clean = {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}
    assert gate.validate("bar", clean).decision == Verdict.PASS

    # OHLC 不一致：high 低于 close
    ohlc_bad = {"open": 10.0, "high": 10.0, "low": 9.5, "close": 10.5, "volume": 1000.0}
    assert gate.validate("bar", ohlc_bad).decision == Verdict.DENY

    # 缺失字段：无 volume
    missing = {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5}
    assert gate.validate("bar", missing).decision == Verdict.DENY

    # 未知 dataset：默认拒绝
    assert gate.validate("unknown_ds", clean).decision == Verdict.DENY


# ===========================================================================
# 验收条 5：多账户隔离
# ===========================================================================


def test_acceptance_multi_account_isolation(tmp_path):
    """§11-5 多账户隔离：acct1 写 acct1 读到、acct2 读不到。
    Position 与 Order 均以 account_id 维度隔离。
    """
    sqlite = SqliteStore(str(tmp_path / "iso.db"))
    sqlite.start()
    try:
        pos_repo = SqlitePositionRepository(sqlite)
        order_repo = SqliteOrderRepository(sqlite)

        # acct1 写入持仓与订单
        pos_repo.upsert("acct-1", "600519.SH", qty=100.0, avg_cost=1800.0)
        order_repo.insert(_order("o-1", "acct-1"))

        # acct1 视角：查得到自己的持仓与订单
        assert pos_repo.get("acct-1", "600519.SH") is not None
        assert {o["order_id"] for o in order_repo.by_account("acct-1")} == {"o-1"}

        # acct2 视角：同 symbol 持仓查不到、订单列表为空
        assert pos_repo.get("acct-2", "600519.SH") is None
        assert order_repo.by_account("acct-2") == []

        # acct2 写入自己的数据，list_by_account / by_account 不串账户
        pos_repo.upsert("acct-2", "000001.SZ", qty=200.0, avg_cost=12.0)
        order_repo.insert(_order("o-2", "acct-2", symbol="000001.SZ"))
        assert {r["symbol"] for r in pos_repo.list_by_account("acct-1")} == {"600519.SH"}
        assert {r["symbol"] for r in pos_repo.list_by_account("acct-2")} == {"000001.SZ"}
        assert {o["order_id"] for o in order_repo.by_account("acct-1")} == {"o-1"}
        assert {o["order_id"] for o in order_repo.by_account("acct-2")} == {"o-2"}
    finally:
        sqlite.stop()


# ===========================================================================
# 验收条 6：调休日历
# ===========================================================================


def test_acceptance_calendar_makeup():
    """§11-6 调休日历：
    - 2024-02-04（春节补班，周日）is_trading_day True
    - 2024-10-01（国庆）is_trading_day False
    """
    cal = TradingCalendar()

    # 补班日：overlay 把本该休的日子补回为交易日
    assert cal.is_trading_day(_dt.date(2024, 2, 4)) is True

    # 国庆节：xcals 已识别为非交易日
    assert cal.is_trading_day(_dt.date(2024, 10, 1)) is False

    # 普通交易日（周一）正常为 True，作为对照
    assert cal.is_trading_day(_dt.date(2024, 6, 17)) is True


# ===========================================================================
# 验收条 7：事件总线
# ===========================================================================


def test_acceptance_event_bus():
    """§11-7 事件总线：publish BarEvent 订阅者收到；订阅者异常相互隔离。"""
    bus = EventBus()
    received: list[BarEvent] = []

    bus.subscribe(BarEvent, received.append)

    # 抛异常的订阅者不应影响其他订阅者
    def boom(_: BarEvent) -> None:
        raise RuntimeError("subscriber boom")

    bus.subscribe(BarEvent, boom)

    evt = BarEvent(
        symbol="600519.SH", freq="1d",
        ts=_dt.datetime(2024, 6, 14, 15, 0, 0),
        close=1820.0, volume=1000.0,
    )
    bus.publish(evt)

    # 正常订阅者仍收到事件，异常订阅者被吞掉
    assert len(received) == 1
    assert received[0] is evt
    assert received[0].symbol == "600519.SH"
    assert received[0].close == 1820.0
