"""因子挖掘 Tester 测试：双门入库（BH-FDR + 经济显著）（设计 v0.5 §4.2.4 / §11 M3）。

覆盖点：
- 强因子（ic 高 / p 小 / novel / 经济显著）→ passed=True
- 随机因子 → ic_below_min + bh_fdr_fail，passed=False
- ic 低于下限 → 'ic_below_min'
- ir 低于下限 → 'ir_below_min'
- BH-FDR（budget 放大后超 alpha）→ 'bh_fdr_fail'
- 与已知因子高相关 → 'novelty_fail'
- 多空年化不达标 → 'long_short_annual_below_min'
- BH-FDR budget 分母：同 p，budget 大 → bh_fdr_p 大（防 optional stopping）
- 多门不过 → reasons 多条

TDD：本文件先于 tester.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.mining.tester import TestConfig, TestResult, Tester


# ---------------------------------------------------------------------------
# 合成长格式 panel 辅助
# ---------------------------------------------------------------------------
RNG = np.random.default_rng(7)
SYMBOLS = [f"S{i:03d}" for i in range(100)]
INDUSTRIES = ["银行", "地产", "医药", "电子", "消费"]
N_DATES = 20
DATES = pd.date_range("2024-01-01", periods=N_DATES, freq="D").astype("int64") // 10**9


def _panel_from(values_fn, n_dates: int = N_DATES) -> pd.DataFrame:
    """生成长格式 panel：列 trade_date / symbol / value。values_fn(date_index) -> np.array[len(SYMBOLS)]。"""
    rows = []
    for i in range(n_dates):
        vals = values_fn(i)
        for s, v in zip(SYMBOLS, vals):
            rows.append((DATES[i], s, float(v)))
    return pd.DataFrame(rows, columns=["trade_date", "symbol", "value"])


def _strong_factor_panel() -> pd.DataFrame:
    """因子截面内单调，加截面间时序波动使 IC 时序有方差（IR 可解）。"""

    def fn(i: int) -> np.ndarray:
        # 截面排序信号 + 小幅噪声（保留强单调，IC 接近 1 但不恒定）
        base = np.arange(len(SYMBOLS), dtype=float)
        return base + RNG.normal(0, 0.5, size=len(SYMBOLS))

    return _panel_from(fn)


def _returns_panel_aligned(factor_panel: pd.DataFrame, slope: float = 0.001) -> pd.DataFrame:
    """收益与因子同序（ic 高）：returns = slope * rank(factor) + 小噪声。

    slope 用日收益率量级（~0.001），保证分层多空年化在合理量级。
    噪声使 IC 时序有方差 → IR 可解。
    """

    def fn(i: int) -> np.ndarray:
        f_vals = factor_panel[factor_panel["trade_date"] == DATES[i]]["value"].to_numpy()
        order = np.argsort(f_vals)
        ranked = np.empty_like(order, dtype=float)
        ranked[order] = np.arange(len(order), dtype=float)
        # rank 标准化后乘 slope，加相对噪声让 IC<1（IR 可解）
        return slope * ranked + RNG.normal(0, slope * 0.3, size=len(order))

    return _panel_from(fn)


def _random_panel(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # 日收益率量级噪声，分层多空期望≈0
    return _panel_from(lambda i: rng.normal(0, 0.01, size=len(SYMBOLS)))


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_strong_factor_passes():
    """ic 高 / p 小 / novel / 经济显著 → passed=True。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    tester = Tester(TestConfig(min_ic=0.03, min_ir=0.5, min_long_short_annual=0.0))
    result = tester.test(
        factor, returns, p_value=0.001, hypothesis_budget=10, known_factor_panels=None
    )
    assert isinstance(result, TestResult)
    assert result.passed is True, f"reasons={result.reasons}, ic={result.ic}, ir={result.ir}"
    assert result.ic >= 0.03
    assert result.ir >= 0.5
    assert result.bh_fdr_p < 0.05
    assert result.reasons == []


def test_random_factor_rejected():
    """随机因子 ic≈0 → ic_below_min + bh_fdr_fail。"""
    factor = _random_panel(seed=1)
    returns = _random_panel(seed=2)
    tester = Tester()
    result = tester.test(factor, returns, p_value=0.5, hypothesis_budget=10)
    assert result.passed is False
    assert "ic_below_min" in result.reasons
    assert "bh_fdr_fail" in result.reasons


def test_ic_below_min():
    """ic=0.02 < 0.03 → 'ic_below_min'。"""
    # 用弱单调因子 + 大噪声使 IC 降到一个明确小于 min 的区间（构造 ic≈0.02 较难，
    # 改用直接验证逻辑：随机因子 ic 接近 0 必然 < min_ic，必含 ic_below_min）
    factor = _random_panel(seed=3)
    returns = _random_panel(seed=4)
    tester = Tester(TestConfig(min_ic=0.03, bh_fdr_alpha=1.0, min_ir=0.0, min_long_short_annual=0.0))
    # alpha=1.0 关掉 BH-FDR 门，min_ir/min_long_short=0 关掉另两门，
    # 突出 ic 门：随机因子 |ic| 必 < 0.03
    result = tester.test(factor, returns, p_value=0.0001, hypothesis_budget=1)
    assert result.passed is False
    assert "ic_below_min" in result.reasons
    assert abs(result.ic) < 0.03


def test_ir_below_min():
    """ir < 0.5 → 'ir_below_min'。"""
    # 因子 ic 较高但 ic 时序噪声极大（ir 低）：每个截面 ic 大幅波动
    # 构造方式：偶数截面强正相关、奇数截面强负相关，mean≈0 → ir 低
    factor = _random_panel(seed=5)
    returns = factor.copy()
    # 奇数截面收益取负
    mask_odd = returns["trade_date"].isin(DATES[1::2])
    returns.loc[mask_odd, "value"] = -returns.loc[mask_odd, "value"]
    tester = Tester(
        TestConfig(min_ic=0.0, bh_fdr_alpha=1.0, min_ir=0.5, min_long_short_annual=0.0)
    )
    result = tester.test(factor, returns, p_value=0.0001, hypothesis_budget=1)
    assert result.passed is False
    assert "ir_below_min" in result.reasons


def test_bh_fdr_fail():
    """p_value=0.01, budget=20 → bh_fdr_p=0.2 > 0.05 → 'bh_fdr_fail'。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    tester = Tester(TestConfig(min_ic=0.0, min_ir=0.0, min_long_short_annual=0.0))
    # 关掉经济/ic/ir 门，只留 BH-FDR 门
    result = tester.test(factor, returns, p_value=0.01, hypothesis_budget=20)
    assert result.bh_fdr_p == 0.01 * 20
    assert result.passed is False
    assert "bh_fdr_fail" in result.reasons


def test_novelty_fail():
    """factor 与 known 高相关（>0.5）→ 'novelty_fail'。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    known = factor.copy()  # 完全相同 → 相关=1
    tester = Tester(
        TestConfig(min_ic=0.0, min_ir=0.0, bh_fdr_alpha=1.0, min_long_short_annual=0.0)
    )
    result = tester.test(factor, returns, known_factor_panels=[known], p_value=0.0001, hypothesis_budget=1)
    assert result.passed is False
    assert result.novelty_is_novel is False
    assert "novelty_fail" in result.reasons


def test_economics_long_short():
    """long_short_annual < min → 'long_short_annual_below_min'。"""
    # 收益全 0：分层多空严格 0，年化必 < min_long_short_annual
    factor = _random_panel(seed=6)
    returns = _panel_from(lambda i: np.zeros(len(SYMBOLS)))
    tester = Tester(
        TestConfig(min_ic=0.0, min_ir=0.0, bh_fdr_alpha=1.0, min_long_short_annual=0.05)
    )
    result = tester.test(factor, returns, p_value=0.0001, hypothesis_budget=1)
    assert result.passed is False
    assert "long_short_annual_below_min" in result.reasons
    assert result.long_short_annual == 0.0


def test_bh_fdr_budget_denominator():
    """同 p_value，budget 大 → bh_fdr_p 大（分母用预算数，防 optional stopping）。"""
    factor = _strong_factor_panel()
    returns = _returns_panel_aligned(factor)
    tester = Tester()
    r_small = tester.test(factor, returns, p_value=0.01, hypothesis_budget=5)
    r_large = tester.test(factor, returns, p_value=0.01, hypothesis_budget=50)
    assert r_large.bh_fdr_p > r_small.bh_fdr_p
    assert r_small.bh_fdr_p == 0.01 * 5
    assert r_large.bh_fdr_p == 0.01 * 50


def test_reasons_collected():
    """多门不过 → reasons 多条。"""
    factor = _random_panel(seed=8)
    returns = _random_panel(seed=9)
    tester = Tester()
    result = tester.test(factor, returns, p_value=0.5, hypothesis_budget=50)
    assert result.passed is False
    # 随机因子 + 大 budget：至少 ic_below_min + bh_fdr_fail + ir_below_min + long_short_annual_below_min
    assert len(result.reasons) >= 3
