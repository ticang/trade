"""交易规则 Provider：按 symbol + 决策时刻查询生效中的交易规则。

设计 v0.5 §4.1.3/§6：
- classify_symbol：当前阶段仅支持沪深主板股票；其他板块/品种返回 unsupported
- rules_for：按 effective_from <= decision_time < effective_to 命中区间行，
  反序列化 rule_json 装 TradingRule 返回；无命中返回 None
- check_no_overlap：校验同 (market,board,product_type) 区间不重叠
  （M0 预留，M0.5 录入 trading_rule 前调用）
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Optional, Sequence

from quant.data.instrument import Instrument
from quant.data.models import TradingRule
from quant.data.sqlite_store import SqliteStore


def classify_symbol(symbol: str) -> tuple[str, str, str]:
    """symbol→(market,board,product_type) 当前范围映射。

    最新设计文档把当前交易范围收窄为沪深主板股票：
    - 6xxxxx→(SSE,main,stock)  沪市主板
    - 00xxxx→(SZSE,main,stock)  深市主板
    - 其他板块/品种→(UNSUPPORTED,unsupported,unsupported)

    科创/创业/北交/ETF/可转债保留为后续扩展，补齐规则来源和
    fixture 后再进入默认路由。
    """
    s = symbol.strip()
    if s.startswith("688"):
        return ("UNSUPPORTED", "unsupported", "unsupported")
    if s.startswith("6"):
        return ("SSE", "main", "stock")
    if s.startswith("00"):
        return ("SZSE", "main", "stock")
    return ("UNSUPPORTED", "unsupported", "unsupported")


def classify_with_instrument(
    symbol: str,
    on: datetime.date,
    instrument: dict[str, Instrument] | None,
) -> tuple[str, str, str]:
    """经 instrument 数据精分类（供 rules_for 使用）。

    - instrument 提供 且 symbol 命中：以 instrument.market/board/product_type 为准；
      * instrument[symbol].is_st(on) → board 改 'st'（命中 st_main 规则）
      * instrument[symbol].etf_crossborder → board 改 'etp_crossborder'
      （ST 与跨境 ETF 互斥：跨境 ETF 无 ST，优先级不影响结果）
    - 否则（instrument 为 None 或 symbol 未命中）回退 classify_symbol(symbol)。
      回退只支持沪深主板，其他板块/品种返回 unsupported。
    """
    if instrument is None:
        return classify_symbol(symbol)
    inst = instrument.get(symbol)
    if inst is None:
        return classify_symbol(symbol)
    market, board, product_type = inst.market, inst.board, inst.product_type
    if inst.is_st(on):
        board = "st"
    elif inst.etf_crossborder:
        board = "etp_crossborder"
    return (market, board, product_type)


class TradingRuleProvider:
    """交易规则查询：依据 symbol 分类后按生效区间命中规则。"""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def rules_for(
        self,
        symbol: str,
        decision_time: datetime.date | datetime.datetime,
        *,
        require_verified: bool = False,
        instrument_provider: object | None = None,
    ) -> Optional[TradingRule]:
        """查 symbol 在 decision_time 生效中的交易规则。

        decision_time 可 date 或 datetime，统一取其 date 部分。
        命中条件：market/board/product_type 三元匹配 且
        effective_from <= decision_time < effective_to（effective_to 为 NULL 视为永不过期）。
        期望至多 1 行命中；多行取 effective_from 最大那条。
        无命中返回 None。

        instrument_provider（设计 v0.5 §4.1.3 instrument 路由）：
        - 提供（非 None）→ 经其 classify(symbol, d) 精分类
          （ST/可转债/跨境 ETF 等基础数据维度命中对应规则）；
        - 不提供 → 走 classify_symbol 前缀映射（向后兼容，既有调用不破）。

        require_verified（实盘语义，设计 v0.5 §11）：
        - False（默认，回测/展示）：命中即返回。
        - True（实盘）：命中后若规则不可完全信任则返回 None 阻断实盘。
          不可信任条件见 _is_live_ready（规则级 source_confidence 非 verified，
          或 rule_json.fees 任一明细 _confidence=provisional）。
        """
        d = (
            decision_time.date()
            if isinstance(decision_time, datetime.datetime)
            else decision_time
        )
        if instrument_provider is not None:
            # 经 instrument 精分类（ST 时变/可转债/跨境 ETF 等）
            market, board, product_type = instrument_provider.classify(symbol, d)
        else:
            market, board, product_type = classify_symbol(symbol)
        ds = d.isoformat()

        # 区间右开：effective_from <= d AND (effective_to IS NULL OR effective_to > d)
        rows = self._store.query_all(
            "SELECT rule_id, market, board, product_type, "
            "effective_from, effective_to, source_url, source_confidence, "
            "rule_json, reviewed_by, reviewed_ts "
            "FROM trading_rule "
            "WHERE market = ? AND board = ? AND product_type = ? "
            "AND effective_from <= ? "
            "AND (effective_to IS NULL OR effective_to > ?) "
            "ORDER BY effective_from DESC",
            (market, board, product_type, ds, ds),
        )
        if not rows:
            return None

        rule = _row_to_rule(rows[0])
        # 实盘路径：不可完全信任则阻断（返回 None）
        if require_verified and not _is_live_ready(rule):
            return None
        return rule

    def check_no_overlap(
        self, rows: Sequence[sqlite3.Row]
    ) -> list[str]:
        """校验给定规则行区间不重叠。

        同 (market,board,product_type) 内任意两条规则的
        [effective_from, effective_to) 不得相交（effective_to 为 NULL 视为 +∞）。
        返回冲突描述列表，空列表表示无冲突。

        M0 预留：M0.5 录入 trading_rule 前调用以应用层校验不重叠约束。
        """
        # 按 (market,board,product_type) 分组
        groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for r in rows:
            key = (
                r["market"],
                _norm(r["board"]),
                _norm(r["product_type"]),
            )
            groups.setdefault(key, []).append(r)

        conflicts: list[str] = []
        for key, group in groups.items():
            group.sort(key=lambda r: r["effective_from"])
            # 区间按 from 排序后：任意相交 ⟺ 相邻相交
            for i in range(len(group) - 1):
                msg = _overlap_desc(key, group[i], group[i + 1])
                if msg:
                    conflicts.append(msg)
        return conflicts


def _norm(v: object) -> str:
    """分组键归一：None→空串，便于按三元组聚类。"""
    return "" if v is None else str(v)


def _parse_date(v: object) -> datetime.date:
    """解析 SQLite DATE 列（可能为 'YYYY-MM-DD' 字符串或 date）。"""
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v
    if isinstance(v, datetime.datetime):
        return v.date()
    return datetime.date.fromisoformat(str(v))


def _overlap_desc(
    key: tuple[str, str, str], a: sqlite3.Row, b: sqlite3.Row
) -> Optional[str]:
    """判断 a、b 区间是否相交，相交则返回描述串。

    区间右开 [from, to)；to 为 NULL 视为 +∞。
    排序后 a.from <= b.from，不相交当且仅当 a.to 存在且 a.to <= b.from。
    """
    a_from = _parse_date(a["effective_from"])
    a_to_raw = a["effective_to"]
    b_from = _parse_date(b["effective_from"])
    b_to_raw = b["effective_to"]

    # a 排前，不相交条件：a.to 非空且 a.to <= b.from
    disjoint = a_to_raw is not None and _parse_date(a_to_raw) <= b_from
    if disjoint:
        return None
    market, board, product_type = key
    return (
        f"区间相交: ({market}/{board}/{product_type}) "
        f"规则 {a['rule_id']} [{a_from}, {a_to_raw}) "
        f"与 规则 {b['rule_id']} [{b_from}, {b_to_raw})"
    )


def _is_live_ready(rule: TradingRule) -> bool:
    """规则是否可完全信任（实盘准入，设计 v0.5 §11）。

    不可完全信任（返回 False）当且仅当任一成立：
    1. 规则级 source_confidence != "verified"（结构未权威）；或
    2. rule_json.fees 中任一明细的 _confidence == "provisional"
       （公共费率未完成 source audit 时阻断实盘）。
    fees 缺失或某明细无 _confidence 键均不视为 provisional，不阻断。
    rule_json 解析失败按不可信任处理。
    """
    if rule.source_confidence != "verified":
        return False
    try:
        payload = json.loads(rule.rule_json)
    except (ValueError, TypeError):
        return False
    fees = payload.get("fees") if isinstance(payload, dict) else None
    if not isinstance(fees, dict):
        return True
    for item in fees.values():
        if isinstance(item, dict) and item.get("_confidence") == "provisional":
            return False
    return True


def _row_to_rule(row: sqlite3.Row) -> TradingRule:
    """从查询行构造 TradingRule；rule_json 保持原始字符串。"""
    return TradingRule(
        rule_id=row["rule_id"],
        market=row["market"],
        board=row["board"],
        product_type=row["product_type"],
        effective_from=_parse_date(row["effective_from"]),
        effective_to=(
            _parse_date(row["effective_to"]) if row["effective_to"] is not None else None
        ),
        source_url=row["source_url"],
        source_confidence=row["source_confidence"],
        rule_json=row["rule_json"],
        reviewed_by=row["reviewed_by"],
        reviewed_ts=row["reviewed_ts"],
    )
