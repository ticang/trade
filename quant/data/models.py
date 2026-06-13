"""数据模型 dataclass。

字段对应设计 v0.5 §6 的 DDL（SQLite 事务库 + DuckDB 数据库）。
仅作类型载体，不承载行为，符合 YAGNI。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Literal, Optional


PitConfidence = Literal["live", "rule_inferred"]


@dataclass
class Instrument:
    """证券基础信息（DuckDB: instrument）。"""

    symbol: str
    market: str
    board: Optional[str]
    product_type: str
    list_date: Optional[datetime.date]
    delist_date: Optional[datetime.date]
    status: str
    source: str
    available_at: Optional[int]
    ingested_at: Optional[int]


@dataclass
class Bar:
    """K 线（DuckDB: bar）。ts/available_at 等为 epoch 毫秒 BIGINT。"""

    symbol: str
    freq: str
    trade_date: datetime.date
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    adj_type: Optional[str]
    source: str
    available_at: Optional[int]
    received_ts: Optional[int]
    ingested_at: Optional[int]
    as_of: Optional[int]
    pit_confidence: PitConfidence


@dataclass
class PointInTime:
    """单字段 PIT 标记（DuckDB: pit_field 的运行时对应物）。"""

    field: str
    value: str
    trade_date: datetime.date
    available_at: int
    source: str
    ingested_at: Optional[int]
    pit_confidence: PitConfidence


@dataclass
class TradingRule:
    """交易规则版本（SQLite: trading_rule）。"""

    rule_id: str
    market: str
    board: Optional[str]
    product_type: Optional[str]
    effective_from: datetime.date
    effective_to: Optional[datetime.date]
    source_url: str
    source_confidence: str
    rule_json: str
    reviewed_by: Optional[str]
    reviewed_ts: Optional[int]


@dataclass
class Account:
    """账户（SQLite: account）。"""

    account_id: str
    broker: str
    env: str
    name: str
