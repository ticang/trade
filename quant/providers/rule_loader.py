"""交易规则种子装载：读 YAML 种子写入 trading_rule 表。

设计 v0.5 §6 录入路径：
- 读 data/rules_v1.yaml（A 股结构性规则种子，置信分层标注）
- 每条 INSERT OR REPLACE INTO trading_rule，rule_json（YAML dict）经 json.dumps 存字符串
- 写后全表查行调 TradingRuleProvider.check_no_overlap 严校验区间不重叠
  （protect 数据完整性：当前种子仅沪深主板股票 + ST 主板）

幂等：INSERT OR REPLACE by rule_id（PK），重复 load 不报错不翻倍。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from quant.data.sqlite_store import SqliteStore
from quant.providers.trading_rule import TradingRuleProvider

# 种子 YAML：当前主板交易规则 v1（结构性规则 verified，费用明细 provisional）
DEFAULT_RULES_YAML = Path(__file__).parent / "data" / "rules_v1.yaml"

# 写入列对齐 schema.trading_rule DDL
_INSERT_SQL = (
    "INSERT OR REPLACE INTO trading_rule "
    "(rule_id, market, board, product_type, effective_from, effective_to, "
    "source_url, source_confidence, rule_json, reviewed_by, reviewed_ts) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# 全表回查列：与 TradingRuleProvider.check_no_overlap 入参一致
_SELECT_ALL_SQL = (
    "SELECT rule_id, market, board, product_type, "
    "effective_from, effective_to FROM trading_rule"
)


def load_rules(
    store: SqliteStore,
    yaml_path: Path | str | None = None,
    *,
    strict_overlap: bool = True,
) -> int:
    """读 YAML 种子写入 trading_rule 表，返回写入条数。

    - yaml_path 默认 DEFAULT_RULES_YAML
    - rule_json（YAML dict）经 json.dumps 存字符串
    - effective_to: null 存 None（SQL NULL）；日期串原样存
    - reviewed_by/reviewed_ts: YAML 可能无此键 → None
    - 写完 flush
    - strict_overlap=True：写后全表查行调 check_no_overlap，非空冲突抛 ValueError
    - 幂等：INSERT OR REPLACE by rule_id
    """
    path = Path(yaml_path) if yaml_path is not None else DEFAULT_RULES_YAML
    with path.open("r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    count = 0
    for r in rules:
        store.execute(
            _INSERT_SQL,
            (
                r["rule_id"],
                r["market"],
                r["board"],
                r["product_type"],
                r["effective_from"],
                r["effective_to"],
                r["source_url"],
                r["source_confidence"],
                json.dumps(r["rule_json"], ensure_ascii=False),
                r.get("reviewed_by"),
                r.get("reviewed_ts"),
            ),
        )
        count += 1

    store.flush(timeout=5.0)

    if strict_overlap:
        rows = store.query_all(_SELECT_ALL_SQL)
        conflicts = TradingRuleProvider(store).check_no_overlap(rows)
        if conflicts:
            raise ValueError("; ".join(conflicts))

    return count
