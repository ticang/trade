"""VaR/CVaR 与 Kupiec POF 回测测试（M5a §4.8.2 多情景稳健性 Task 6）。

校验损失分位、尾部期望、覆盖率回测的统计正确性。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from quant.replay.var import (
    conditional_var,
    kupiec_pof,
    value_at_risk,
    var_backtest,
)


def _normal_paths(n: int = 10000, seed: int = 0) -> np.ndarray:
    """均值 0、标准差 1 的正态盈亏路径。"""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n)


def test_var_quantile():
    """VaR_95 应等于 pnl 下 5% 分位的相反数（损失额）。"""
    paths = _normal_paths()
    var = value_at_risk(paths, alpha=0.95)
    expected = -float(np.percentile(paths, 5))
    assert var == pytest.approx(expected, abs=1e-9)


def test_var_positive_loss():
    """VaR 应返回正数（损失额），对零均值正态其下分位为负、取反为正。"""
    paths = _normal_paths()
    var = value_at_risk(paths, alpha=0.95)
    assert var > 0


def test_cvar_ge_var():
    """CVaR（尾部平均损失）应不小于 VaR。"""
    paths = _normal_paths()
    var = value_at_risk(paths, alpha=0.95)
    cvar = conditional_var(paths, alpha=0.95)
    assert cvar >= var - 1e-9


def test_kupiec_pof_correct_coverage():
    """实际例外率接近 1-alpha（5% at 95%）→ p_value>0.05（不拒绝，达标）。"""
    n, x = 500, 25  # 实际例外率 5%，恰好等于理论值
    lr, p = kupiec_pof(x, n, alpha=0.95)
    assert p > 0.05
    assert lr == pytest.approx(0.0, abs=1e-6)


def test_kupiec_pof_rejects_bad_coverage():
    """例外率 20% 远偏离 5%（at 95%）→ p_value<0.05（拒绝，覆盖率不达标）。"""
    n, x = 500, 100
    lr, p = kupiec_pof(x, n, alpha=0.95)
    assert p < 0.05
    assert lr > 3.84  # Chi2(1) 5% 临界值


def test_kupiec_formula():
    """手算对照：x=2, n=10, alpha=0.95 → LR≈2.7956, p≈0.0945。"""
    lr, p = kupiec_pof(2, 10, alpha=0.95)
    # 手算：ll_null = 8*log(0.95)+2*log(0.05); ll_alt = 8*log(0.8)+2*log(0.2)
    ll_null = 8 * math.log(0.95) + 2 * math.log(0.05)
    ll_alt = 8 * math.log(0.8) + 2 * math.log(0.2)
    expected_lr = -2 * ll_null + 2 * ll_alt
    assert lr == pytest.approx(expected_lr, abs=1e-9)
    assert lr == pytest.approx(2.7956, abs=1e-3)


def test_var_backtest_structure():
    """返回 dict 应包含全部字段；coverage_ok 与 p_value 一致。"""
    rng = np.random.default_rng(1)
    pnl = rng.standard_normal(500)
    # 构造 VaR 预测使例外率接近 5%
    forecast = np.full(500, 1.645)  # 95% 正态分位
    result = var_backtest(pnl, forecast, alpha=0.95)
    assert set(result) == {
        "exceptions",
        "exception_rate",
        "lr_stat",
        "p_value",
        "coverage_ok",
    }
    assert isinstance(result["exceptions"], (int, np.integer))
    assert isinstance(result["exception_rate"], float)
    assert isinstance(result["lr_stat"], float)
    assert isinstance(result["p_value"], float)
    expected_ok = result["p_value"] > 0.05
    assert result["coverage_ok"] == expected_ok


def test_var_backtest_perfect():
    """VaR 预测全很大（0 例外）at 95% 大样本 → Kupiec 应拒绝（达标判定为 False）。"""
    rng = np.random.default_rng(2)
    pnl = rng.standard_normal(500)  # 范围约 [-3.5, 3.5]
    forecast = np.full(500, 100.0)  # 远超最大损失，0 例外
    result = var_backtest(pnl, forecast, alpha=0.95)
    assert result["exceptions"] == 0
    assert result["exception_rate"] == 0.0
    # 0 例外 at 95% 大样本：过度保守，Kupiec 应拒绝
    assert result["p_value"] < 0.05
    assert result["coverage_ok"] is False
