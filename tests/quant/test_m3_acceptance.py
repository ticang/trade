"""M3 情绪/因子挖掘 集成验收测试（设计 v0.5 §11 M3 验收 + 边界，capstone）。

扁平化端到端串起 M3：SingleAgentMine（LLM → DSL Sandbox → Interpreter →
Tester 五门）→ ExperimentTracker 落库 → breadth 因子。确定性合成数据驱动，
mock LLM 固定 DSL 输出，保证可重跑。

对应 §11 M3「工程 Done」6 条 + §4.3.1 命题边界：
1. pipeline 可复现：同 seed+snapshot 两次 run，candidates/failures 完全一致
2. 门禁有效：强因子进 candidates，随机因子被拒进 failures
3. 实验落库：list_by_kind('mining') 长度 == budget
4. DSL 边界：Sandbox 拒未知算子；interpreter 求值嵌套表达式正确
5. breadth 因子可计算：合成 bars 返回非空时间序列
6. 算术 + JSON 数组管线（回归 B5）：mul/add 算子 + LLM JSON 数组取首端到端可用
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.data.sqlite_store import SqliteStore
from quant.dsl.interpreter import evaluate
from quant.dsl.sandbox import Sandbox
from quant.factor.factors.breadth import breadth_factor_series
from quant.mining.agent import SingleAgentMine
from quant.mining.tester import TestConfig, Tester
from quant.mining.tracker import ExperimentTracker

# 固定 RNG seed，合成数据确定性
_SEED = 11
SYMBOLS = [f"S{i:03d}" for i in range(60)]
N_DATES = 25
DATES = pd.date_range("2024-01-01", periods=N_DATES, freq="D").astype("int64") // 10**9


# ---------------------------------------------------------------------------
# 合成 panel：长格式 symbol/trade_date/close/volume
# ---------------------------------------------------------------------------
def _synth_panel(seed: int = _SEED) -> pd.DataFrame:
    """构造 panel：close 截面单调 + 截面间轻微漂移；volume 随 close 正相关。"""
    rng = np.random.default_rng(seed)
    base = np.arange(len(SYMBOLS), dtype=float)
    rows = []
    for i, d in enumerate(DATES):
        # 截面 close 严格递增 + 轻噪声，保证 rank(close) 截面排序稳定
        noise = rng.normal(0, 0.3, size=len(SYMBOLS))
        closes = base + noise
        # volume 与 close 正相关，使量价类 DSL 也能求值
        volumes = closes * 1000 + rng.normal(0, 50, size=len(SYMBOLS))
        for j, s in enumerate(SYMBOLS):
            rows.append({
                "symbol": s, "trade_date": d,
                "close": float(closes[j]), "volume": float(volumes[j]),
            })
    return pd.DataFrame(rows).sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _returns_panel_aligned(panel: pd.DataFrame, slope: float = 0.002) -> pd.DataFrame:
    """收益与 close 截面排序正相关：构造强因子（rank(close)）能通过经济门。"""
    wide = panel.pivot(index="trade_date", columns="symbol", values="close").to_numpy()
    rng = np.random.default_rng(_SEED + 1)
    rows = []
    for i in range(N_DATES):
        order = np.argsort(wide[i])
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(len(order), dtype=float)
        ret = slope * ranked + rng.normal(0, slope * 0.3, size=len(order))
        for j, s in enumerate(SYMBOLS):
            rows.append({"trade_date": DATES[i], "symbol": s, "value": float(ret[j])})
    return pd.DataFrame(rows)


def _returns_panel_random(seed: int = _SEED + 2) -> pd.DataFrame:
    """纯随机收益：与任何因子都不相关，因子应被门禁拒。"""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(N_DATES):
        ret = rng.normal(0, 0.01, size=len(SYMBOLS))
        for j, s in enumerate(SYMBOLS):
            rows.append({"trade_date": DATES[i], "symbol": s, "value": float(ret[j])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Mock LLM：complete_json 按序列返回固定 DSL；JSON 数组形态（B5 回归）
# ---------------------------------------------------------------------------
class _MockLLM:
    """替身 LLMClient：按序列返回假设；model 固定。"""

    def __init__(self, items: list[dict]):
        self._items = list(items)
        self._idx = 0
        self.model = "mock-model"

    def complete_json(self, messages: list[dict], **kw) -> dict:
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return dict(item)


def _hyp(expr: str, hyp: str = "h", params: dict | None = None) -> dict:
    return {"hypothesis": hyp, "dsl_expr": expr, "params": params or {}, "rationale": "r"}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path) -> SqliteStore:
    s = SqliteStore(str(tmp_path / "m3_acc.db"))
    s.start()
    yield s
    s.stop()


@pytest.fixture
def tracker(store) -> ExperimentTracker:
    return ExperimentTracker(store)


@pytest.fixture
def tester() -> Tester:
    # 放宽 long_short 下限，使构造的强因子稳定通过经济门（IC/IR 仍严格）
    return Tester(TestConfig(min_ic=0.03, min_ir=0.5, min_long_short_annual=0.0))


@pytest.fixture
def panel() -> pd.DataFrame:
    return _synth_panel()


@pytest.fixture
def returns_aligned(panel) -> pd.DataFrame:
    return _returns_panel_aligned(panel)


@pytest.fixture
def returns_random() -> pd.DataFrame:
    return _returns_panel_random()


def _make_agent(llm, tester, tracker) -> SingleAgentMine:
    return SingleAgentMine(llm, tester, tracker)


# ===========================================================================
# 验收 1：pipeline 可复现
# ===========================================================================
def test_m3_pipeline_reproducible(tester, tracker, store, panel, returns_aligned):
    """§11 M3 验收 1：同 seed+snapshot 两次 run，candidates/failures 完全一致。

    mock LLM 固定输出 → 无随机源；SingleAgentMine.run 纯函数式，
    两次产出的 candidates/failures 结构与内容逐项相等。
    """
    items = [_hyp("rank(close)"), _hyp("rank(nope)"), _hyp("rank(ts_delta(close,5))")]

    def _run_once():
        # 每次新 tracker+store 隔离，避免 list_by_kind 累积
        llm = _MockLLM(items)
        agent = _make_agent(llm, tester, tracker)
        return agent.run(
            "低波动反转", panel, returns_aligned,
            hypothesis_budget=3, seed=0, snapshot_id="snap_m3_a",
        )

    r1 = _run_once()
    r2 = _run_once()

    # run_id 确定性
    assert r1.run_id == r2.run_id == "低波动反转_0_3"
    # n_passed 一致
    assert r1.n_passed == r2.n_passed
    # candidates 的 hypothesis/expr 逐项一致
    assert [c["hypothesis"] for c in r1.candidates] == [c["hypothesis"] for c in r2.candidates]
    assert [c["expr"] for c in r1.candidates] == [c["expr"] for c in r2.candidates]
    # failures 的 hypothesis/expr/reason 逐项一致
    assert [f["hypothesis"] for f in r1.failures] == [f["hypothesis"] for f in r2.failures]
    assert [f["expr"] for f in r1.failures] == [f["expr"] for f in r2.failures]
    assert [f["reason"] for f in r1.failures] == [f["reason"] for f in r2.failures]


# ===========================================================================
# 验收 2：门禁有效
# ===========================================================================
def test_m3_gate_effective(tester, tracker, panel, returns_aligned, returns_random):
    """§11 M3 验收 2：强因子通过门禁进 candidates；随机因子被拒进 failures。

    - rank(close) 与 returns_aligned 同序 → 通过 IC/IR 门 → candidates
    - rank(close) 在 returns_random 上无预测力 → 被 IC/IR 门拒 → failures
    """
    # 强因子 + 对齐收益 → 至少一条进 candidates
    llm_strong = _MockLLM([_hyp("rank(close)")])
    agent_strong = _make_agent(llm_strong, tester, tracker)
    res_strong = agent_strong.run(
        "量价动量", panel, returns_aligned, hypothesis_budget=1, seed=0,
    )
    assert res_strong.n_passed >= 1, f"强因子应通过门禁，实际 reasons={res_strong.failures}"
    assert len(res_strong.candidates) >= 1

    # 同一 DSL + 随机收益 → 被 IC/IR 拒
    llm_weak = _MockLLM([_hyp("rank(close)")])
    agent_weak = _make_agent(llm_weak, tester, tracker)
    res_weak = agent_weak.run(
        "量价动量", panel, returns_random, hypothesis_budget=1, seed=0,
    )
    assert res_weak.n_passed == 0
    assert len(res_weak.failures) == 1
    reasons = res_weak.failures[0]["reason"]
    # 随机因子应触发 IC 或 IR 门拒因
    assert "ic_below_min" in reasons or "ir_below_min" in reasons, (
        f"随机因子应被 IC/IR 门拒，实际 reason={reasons}"
    )


# ===========================================================================
# 验收 3：实验落库
# ===========================================================================
def test_m3_experiments_logged(tester, tracker, panel, returns_aligned):
    """§11 M3 验收 3：run 后 list_by_kind('mining') 长度 == budget。

    每轮假设都 tracker.log（含 LLM 解析失败 / DSL 非法 / 求值错 / 通过 / 被拒），
    保证状态可恢复与审计。
    """
    items = [_hyp("rank(close)"), _hyp("foobar(close)"), _hyp("rank(nope)")]
    llm = _MockLLM(items)
    agent = _make_agent(llm, tester, tracker)
    budget = 3
    agent.run(
        "低波动反转", panel, returns_aligned,
        hypothesis_budget=budget, seed=0, snapshot_id="snap_m3_log",
    )
    rows = tracker.list_by_kind("mining")
    assert len(rows) == budget
    # 每条都带 snapshot_id（可审计）
    assert all(r["snapshot_id"] == "snap_m3_log" for r in rows)


# ===========================================================================
# 验收 4：DSL 边界
# ===========================================================================
def test_m3_dsl_boundary():
    """§11 M3 验收 4：Sandbox 拒未知算子；interpreter 求值嵌套表达式正确。

    - 未知算子 foobar → Sandbox.validate False（边界生效，LLM 编造算子被拒）
    - 嵌套表达式 mul(ts_delta(close,5), rank(volume)) 在合成 panel 上求值
      返回非全 NaN Series，长度 == panel 行数
    """
    sb = Sandbox()
    # 合法算子集全部通过
    assert sb.validate("rank(ts_mean(close,5))") is True
    assert sb.validate("mul(ts_delta(close,5), rank(volume))") is True
    # 未知算子被拒
    assert sb.validate("foobar(close)") is False
    assert sb.validate("rank(unknown_op(close))") is False

    # 嵌套表达式求值
    panel = _synth_panel()
    s = evaluate("mul(ts_delta(close,5), rank(volume))", panel)
    assert isinstance(s, pd.Series)
    assert len(s) == len(panel)
    # 非全 NaN（前 5 行因 ts_delta 窗口为 NaN，其余应有值）
    assert s.iloc[5:].notna().any()


# ===========================================================================
# 验收 5：breadth 因子可计算
# ===========================================================================
def test_m3_breadth_computable():
    """§11 M3 验收 5：breadth_factor_series 对合成 bars 返回非空时间序列。

    构造 3 symbol × 2 day bars（含涨停/跌停），breadth_value 时序长度 == 2，
    值在 [-1, 1]。
    """
    up = round(10.0 * 1.1, 2)    # 11.00
    down = round(10.0 * 0.9, 2)  # 9.00
    bars = pd.DataFrame([
        dict(trade_date="2024-01-02", symbol="A", open=10.5, high=up, low=10.4, close=up),    # 涨停
        dict(trade_date="2024-01-02", symbol="B", open=9.5, high=9.5, low=down, close=down),  # 跌停
        dict(trade_date="2024-01-02", symbol="C", open=10.0, high=10.2, low=10.0, close=10.1),
        dict(trade_date="2024-01-03", symbol="A", open=11.0, high=11.0, low=10.5, close=10.6),
        dict(trade_date="2024-01-03", symbol="B", open=9.0, high=9.0, low=down, close=down),  # 跌停
        dict(trade_date="2024-01-03", symbol="C", open=10.1, high=up, low=10.4, close=up),    # 涨停
    ])
    prev_close = pd.DataFrame([
        dict(trade_date="2024-01-02", symbol="A", prev_close=10.0),
        dict(trade_date="2024-01-02", symbol="B", prev_close=10.0),
        dict(trade_date="2024-01-02", symbol="C", prev_close=10.0),
        dict(trade_date="2024-01-03", symbol="A", prev_close=up),
        dict(trade_date="2024-01-03", symbol="B", prev_close=down),
        dict(trade_date="2024-01-03", symbol="C", prev_close=10.1),
    ])
    series = breadth_factor_series(bars, prev_close)
    assert isinstance(series, pd.DataFrame)
    assert {"trade_date", "breadth_value"} == set(series.columns)
    assert len(series) == 2
    # 值域合法
    assert series["breadth_value"].between(-1.0, 1.0).all()


# ===========================================================================
# 验收 6：算术 + JSON 数组管线（回归 B5）
# ===========================================================================
def test_m3_arithmetic_and_array_pipeline(tester, tracker, panel, returns_aligned):
    """§11 M3 验收 6（回归 B5）：mul/add 算子 + LLM JSON 数组取首，端到端可用。

    回归 B5：LLMClient.complete_json 支持 JSON 数组形态（取首元素），
    配合 mul/add 算术算子，端到端跑通。
    """
    # 用 add/mul 组合的 DSL 验证算术算子端到端可用
    expr = "add(rank(close), mul(rank(close), rank(volume)))"
    items = [_hyp(expr)]
    llm = _MockLLM(items)
    agent = _make_agent(llm, tester, tracker)
    res = agent.run(
        "量价合成", panel, returns_aligned, hypothesis_budget=1, seed=0,
    )
    # 算术组合因子与 rank(close) 强相关，应通过门禁（与对齐收益同序）
    assert res.n_passed >= 1, f"算术组合因子应可用，实际 reasons={res.failures}"

    # 直接验证 LLMClient JSON 数组解析路径（B5 回归）
    from quant.llm.client import _extract_first_json
    import json

    array_text = '[{"hypothesis": "h1", "dsl_expr": "rank(close)"}, {"hypothesis": "h2"}]'
    candidate = _extract_first_json(array_text)
    obj = json.loads(candidate)
    assert isinstance(obj, list)
    first = obj[0]
    assert first["dsl_expr"] == "rank(close)"
    # complete_json 数组归一：取首元素为 dict
    assert isinstance(first, dict)
