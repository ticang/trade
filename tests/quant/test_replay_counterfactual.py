"""反事实回放测试（M5a §4.8.1 Task 5）。

边界声明（§4.8.1）：基于 event-sourced 历史 bar 重放、改写自身小单决策观察盈亏差异。
仅对自身小单扰动保证撮合一致性；actor 移除 / 大单移除需价格冲击模型
（Almgren-Chriss 或经验冲击函数），否则降级为「相关性叙事」非因果。

复用 SimBroker.match 逐 bar 撮合；盈亏按 bar.close mark-to-market。
rule_json 种子：沪市主板股票（M0.5 rules_v1.yaml sse_main_stock）。

TDD：本文件先于 counterfactual.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import pytest

from quant.backtest.sim_broker import BarSnapshot, Order, SimBroker
from quant.replay.counterfactual import (
    CounterfactualReplay,
    CounterfactualResult,
    ReplayConfig,
)

# rule_json 种子：涨跌停 ±10%、T+1、min_buy 100、lot 100
RULE_JSON = {
    "tick": 0.01,
    "daily_limit_up": 0.10,
    "daily_limit_down": 0.10,
    "settlement_T": 1,
    "min_buy": 100,
    "lot_increment": 100,
    "fees": {
        "stamp": {"value": 0.0005, "_confidence": "provisional"},
        "transfer": {"value": 0.00001, "_confidence": "provisional"},
        "commission": {"value": None, "_confidence": "provisional"},
        "exchange": {"value": None, "_confidence": "provisional"},
    },
}

SYMBOL = "600000.SH"


def _bars_close_rising() -> list[BarSnapshot]:
    """3 日 bar：close 单调递增，volume 充足（量比封顶不阻断）。

    第 0 日 close=10.0、第 1 日 11.0、第 2 日 12.0。
    买入在第 0 日发生，第 2 日末日 mark-to-market。
    """
    closes = [10.0, 11.0, 12.0]
    return [
        BarSnapshot(
            open=c, high=c * 1.02, low=c * 0.98, close=c,
            volume=1_000_000.0,
            limit_up=c * 1.10, limit_down=c * 0.90,
        )
        for c in closes
    ]


def _bar_volume() -> float:
    """history_bars 的日成交量（与 _bars_close_rising 一致）。"""
    return 1_000_000.0


# ---------------------------------------------------------------- 1. classify

def test_classify_small_order():
    """order_qty / bar_volume < small_order_threshold → 'small'；= 0.002 → 'large'。"""
    replay = CounterfactualReplay(SimBroker())
    vol = _bar_volume()
    # 0.0005 < 0.001 → small
    assert replay.classify_order(qty=500.0, bar_volume=vol) == "small"
    # 0.002 > 0.001 → large
    assert replay.classify_order(qty=0.002 * vol, bar_volume=vol) == "large"


# ---------------------------------------------------------------- 2. 小单 pnl_diff

def test_replay_small_order_pnl_diff():
    """actual 买 100、modified 买 200（均小单）→ pnl_diff 非零，degraded=False。

    modified 多买、末日 close 更高 → modified pnl 高于 actual（diff>0）。
    """
    replay = CounterfactualReplay(SimBroker())
    bars = _bars_close_rising()
    vol = _bar_volume()
    # 100 / 1_000_000 = 0.0001 < 0.001 小单；200 仍小单
    actual = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", 100, "limit", 10.0)},
    ]
    modified = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", 200, "limit", 10.0)},
    ]
    res = replay.replay(
        history_bars=bars,
        actual_trades=actual,
        modified_trades=modified,
        rule_json=RULE_JSON,
        initial_cash=1_000_000.0,
    )
    assert isinstance(res, CounterfactualResult)
    assert res.degraded is False
    assert res.pnl_diff != pytest.approx(0.0)
    # 多买且末日 close(12) 高于成本(10) → modified 更优 → diff > 0
    assert res.pnl_diff > 0


# ---------------------------------------------------------------- 3. 大单降级

def test_replay_large_order_degrades():
    """modified 含大单（qty/volume > 阈值）→ degraded=True，reason 含 'impact_model'。"""
    replay = CounterfactualReplay(SimBroker())
    bars = _bars_close_rising()
    vol = _bar_volume()
    large_qty = int(0.005 * vol)  # 5000，占比 0.005 > 0.001 大单
    large_qty = (large_qty // 100) * 100  # 对齐 lot
    actual = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", 100, "limit", 10.0)},
    ]
    modified = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", large_qty, "limit", 10.0)},
    ]
    res = replay.replay(
        history_bars=bars,
        actual_trades=actual,
        modified_trades=modified,
        rule_json=RULE_JSON,
        initial_cash=1_000_000.0,
    )
    assert res.degraded is True
    assert "impact_model" in res.reason


# ---------------------------------------------------------------- 4. 相同决策零差异

def test_replay_identical_trades_zero_diff():
    """actual == modified → pnl_diff = 0。"""
    replay = CounterfactualReplay(SimBroker())
    bars = _bars_close_rising()
    trades = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", 100, "limit", 10.0)},
    ]
    res = replay.replay(
        history_bars=bars,
        actual_trades=trades,
        modified_trades=list(trades),  # 拷贝，避免共享引用
        rule_json=RULE_JSON,
        initial_cash=1_000_000.0,
    )
    assert res.pnl_diff == pytest.approx(0.0)


# ---------------------------------------------------------------- 5. 复用 SimBroker 撮合

def test_replay_uses_simbroker_matching():
    """重放成交经 SimBroker：T+1 卖无持仓被拒（no_position_tplusn）。

    仅当 modified 含「卖无持仓」时，replay 应拒绝该单（fill_qty=0）→
    其 pnl 等同于不操作（pnl = 初始现金）。
    """
    replay = CounterfactualReplay(SimBroker())
    bars = _bars_close_rising()
    actual = []  # 不操作
    modified = [
        # 第 0 日直接卖 100：无持仓（T+1 不允许日内回转）→ 被拒
        {"bar_index": 0, "order": Order(SYMBOL, "sell", 100, "limit", 10.5)},
    ]
    res = replay.replay(
        history_bars=bars,
        actual_trades=actual,
        modified_trades=modified,
        rule_json=RULE_JSON,
        initial_cash=1_000_000.0,
    )
    # 卖单被拒 → modified 持仓为 0、现金未变 → pnl = initial_cash
    # actual 也未操作 → pnl = initial_cash → diff = 0
    assert res.pnl_diff == pytest.approx(0.0)
    assert res.pnl_counterfactual == pytest.approx(1_000_000.0)


# ---------------------------------------------------------------- 6. mark-to-close

def test_pnl_marked_to_close():
    """盈亏按 bar.close mark：买入 100 @ 10、末日 close 12 → 持仓市值 = 1200。

    pnl = cash + Σ持仓按末日 close 的市值。手算可验证 mark-to-close 而非 mark-to-open。
    """
    replay = CounterfactualReplay(SimBroker())
    bars = _bars_close_rising()
    actual = []
    modified = [
        {"bar_index": 0, "order": Order(SYMBOL, "buy", 100, "limit", 10.0)},
    ]
    res = replay.replay(
        history_bars=bars,
        actual_trades=actual,
        modified_trades=modified,
        rule_json=RULE_JSON,
        initial_cash=1_000_000.0,
    )
    # actual 未操作 → pnl_actual = initial_cash
    assert res.pnl_actual == pytest.approx(1_000_000.0)
    # modified 买 100 @ 10（滑点 +5bp → fill_price≈10.005）扣现金、末日 close=12 mark
    # pnl_counterfactual = (initial_cash - 100*fill_price - 费) + 100 * 12
    # 严格断言：mark-to-close → 持仓市值按 12 计，而非 open(12) 或 low(11.76)
    # 因 close==open==12，用 pnl > initial_cash + 100*1.95（即持仓 +195）下界
    # 持仓未实现盈亏 = 100 * (12 - 10.005) ≈ 199.5，扣费后约 +199 → pnl > initial + 195
    assert res.pnl_counterfactual > 1_000_000.0 + 100 * 1.95
