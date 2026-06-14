"""交易规则 golden cases（设计 v0.5 §4.1.6）。

设计意图：规则变更需人工 golden cases 标注——独立于规则表自验，
避免「用规则表自身生成的值校验规则表」的循环论证。本文件的所有
预期值均来自人工核验（对照各交易所规则文档与现行政策），作为
「输入 symbol + 决策时刻 → 预期命中规则事实」的固化契约。

字段约定：daily_limit_down 在 rule_json 中存「跌幅幅度的绝对值」
（如 0.10 表示 −10%），与 daily_limit_up 同号。golden case 断言
的是「人工核验后落库的真实值」，非规则表派生值。

已知局限（诚实记录，非缺陷）：
- ST/*ST 股票的 ±5% 限制需基础数据「ST 标记」配合路由，classify_symbol
  仅按 symbol 前缀无法识别 ST 状态。本测试覆盖该局限：对 ST 标记股
  返回的是默认主板规则（±10%）而非 ST 规则（±5%）。需 instrument 级
  ST/品种标记，留 M1。
- 可转债同理：classify 不路由可转债代码（以 11/12 开头被归为默认主板），
  返回主板规则而非可转债规则。
"""
from __future__ import annotations

import datetime
import json

import pytest

from quant.data.sqlite_store import SqliteStore
from quant.providers.rule_loader import load_rules
from quant.providers.trading_rule import TradingRuleProvider


@pytest.fixture
def store(tmp_db):
    """起停一个 SqliteStore，确保用例结束线程被回收。"""
    sqlite_path, _ = tmp_db
    s = SqliteStore(str(sqlite_path))
    s.start()
    load_rules(s)  # 装入种子规则（10 条）
    yield s
    s.stop()


def _rule_json(store: SqliteStore, symbol: str, when: datetime.date) -> dict:
    """rules_for 命中后返回 rule_json 反序列化后的 dict。"""
    p = TradingRuleProvider(store)
    hit = p.rules_for(symbol, when, require_verified=False)
    assert hit is not None, f"{symbol} @ {when} 未命中任何规则"
    return json.loads(hit.rule_json)


# ============================================================
# Golden case 1：沪市主板（600519 贵州茅台）
# 人工核验：tick=0.01，涨/跌停 ±10%，T+1，最小买入 100 股。
# ============================================================
def test_golden_sse_main_stock(store):
    """600519 @2024-06-14 命中 sse_main_stock，关键字段人工核验值。"""
    rule = _rule_json(store, "600519", datetime.date(2024, 6, 14))

    assert rule["tick"] == 0.01
    assert rule["daily_limit_up"] == 0.10
    # daily_limit_down 存跌幅幅度的绝对值（0.10 表示 −10%）
    assert rule["daily_limit_down"] == 0.10
    assert rule["settlement_T"] == 1
    assert rule["min_buy"] == 100


# ============================================================
# Golden case 2：科创板（688981 中芯国际）
# 人工核验：涨/跌停 ±20%，最小买入 200 股，递增单位 1 股。
# ============================================================
def test_golden_sse_star_stock(store):
    """688981 @2024-06-14 命中 sse_star_stock，关键字段人工核验值。"""
    rule = _rule_json(store, "688981", datetime.date(2024, 6, 14))

    assert rule["daily_limit_up"] == 0.20
    assert rule["min_buy"] == 200
    assert rule["lot_increment"] == 1


# ============================================================
# Golden case 3：创业板（300750 宁德时代）改革前后区间切换
# 人工核验：2020-08-24 起改革为 ±20%；改革前（2020-01-01~2020-08-23）为 ±10%。
# ============================================================
def test_golden_szse_chinext_post_reform(store):
    """300750 @2024-06-14（改革后）命中 szse_chinext_stock_post_reform，±20%。"""
    rule = _rule_json(store, "300750", datetime.date(2024, 6, 14))

    assert rule["daily_limit_up"] == 0.20


def test_golden_szse_chinext_pre_reform(store):
    """300750 @2020-01-06（改革前区间 2020-01-01~2020-08-23）命中
    szse_chinext_stock_pre_reform，±10%。

    验证 effective_from/effective_to 区间右开切换：同 symbol 在不同
    决策时刻命中不同规则版本，是规则版本化的核心契约。
    """
    rule = _rule_json(store, "300750", datetime.date(2020, 1, 6))

    assert rule["daily_limit_up"] == 0.10


# ============================================================
# Golden case 4：北交所（830799）
# 人工核验：涨/跌停 ±30%，最小买入 100 股，递增单位 1 股。
# ============================================================
def test_golden_bse_stock(store):
    """830799 @2024-06-14 命中 bse_stock，关键字段人工核验值。"""
    rule = _rule_json(store, "830799", datetime.date(2024, 6, 14))

    assert rule["daily_limit_up"] == 0.30
    assert rule["min_buy"] == 100
    assert rule["lot_increment"] == 1


# ============================================================
# Golden case 5：普通 ETF（510300 沪深 300ETF）
# 人工核验：涨/跌停 ±10%，T+1 回转。
# ============================================================
def test_golden_etf_normal(store):
    """510300 @2024-06-14 命中 etf_normal，关键字段人工核验值。"""
    rule = _rule_json(store, "510300", datetime.date(2024, 6, 14))

    assert rule["daily_limit_up"] == 0.10
    assert rule["settlement_T"] == 1


# ============================================================
# 已知局限：ST/可转债 不经 symbol 路由（诚实记录，非缺陷）
# classify_symbol 仅按前缀分类，无法识别 ST 标记或可转债品种，
# 需 instrument 级标记数据配合，留 M1。
# ============================================================
def test_st_and_convertible_not_routed_via_symbol(store):
    """ST 标记股/可转债代码经 symbol 路由命中默认主板规则（±10%），
    而非 ST 规则（±5%）或可转债规则（±20%）。

    这是 classify_symbol 的已知局限：无法仅凭 symbol 识别 ST 状态或
    可转债品种，需 instrument 级 ST/品种标记数据配合，路由逻辑留 M1。
    断言其返回主板规则而非 ST/可转债规则，固化当前行为契约。
    """
    p = TradingRuleProvider(store)

    # ST 标记股（600000 浦发银行，假设某段被 ST）：classify 按 6→SSE/main/stock
    st_hit = p.rules_for("600000", datetime.date(2024, 6, 14))
    assert st_hit is not None
    st_rule = json.loads(st_hit.rule_json)
    # 应为 ±10%（主板），而非 ±5%（ST）——ST 规则未被路由命中
    assert st_rule["daily_limit_up"] == 0.10
    assert st_rule["daily_limit_up"] != 0.05  # 非 ST 规则

    # 可转债（113001 以 11 开头）：classify 按 11→开头 1 不匹配任何前缀，
    # 落入默认 (SSE, main, stock)，命中主板规则而非可转债规则
    cb_hit = p.rules_for("113001", datetime.date(2024, 6, 14))
    assert cb_hit is not None
    cb_rule = json.loads(cb_hit.rule_json)
    # 应为 ±10%（主板 T+1），而非 ±20%（可转债 T+0）
    assert cb_rule["daily_limit_up"] == 0.10
    assert cb_rule["settlement_T"] == 1
    # 非可转债规则（可转债 settlement_T=0）
    assert cb_rule["settlement_T"] != 0
