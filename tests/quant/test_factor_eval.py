"""因子评价测试：rank IC + 行业/log 市值中性化残差（设计 v0.5 §4.2.3）。

覆盖点：
- neutralize 完全剥离由 industry+log(mktcap) 线性决定的收益（残差≈0）
- neutralize 保留已知 alpha（残差≈alpha）
- rank_ic 纯噪声 → |IC| 小
- rank_ic 强单调因子 → IC 接近 1
- rank_ic 中性化后 IC 反映纯 alpha（中性化前后 IC 不同）
- rank_ic_series 逐截面算 IC，返回 Series 长度=trade_date 数
- 样本不足（<2）→ nan

TDD：本文件先于 eval.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.factor.eval import (
    decile_returns,
    ic_decay,
    information_ratio,
    neutralize,
    novelty_check,
    rank_ic,
    rank_ic_series,
)


# ---------------------------------------------------------------------------
# 合成数据辅助
# ---------------------------------------------------------------------------
RNG = np.random.default_rng(42)
SYMBOLS = [f"S{i:03d}" for i in range(20)]
INDUSTRIES = ["银行", "地产", "医药", "电子", "消费"]


def _make_indexed(values: np.ndarray | list, name: str | None = None) -> pd.Series:
    return pd.Series(values, index=pd.Index(SYMBOLS[: len(values)], name="symbol"), name=name)


def _make_panel() -> tuple[pd.Series, pd.Series, pd.Series]:
    """合成截面：industry（分类）/ mktcap（市值）/ forward_returns。"""
    industry = pd.Series(
        [INDUSTRIES[i % len(INDUSTRIES)] for i in range(len(SYMBOLS))],
        index=pd.Index(SYMBOLS, name="symbol"),
        name="industry",
    )
    mktcap = pd.Series(
        RNG.uniform(1e9, 1e11, size=len(SYMBOLS)),
        index=pd.Index(SYMBOLS, name="symbol"),
        name="mktcap",
    )
    returns = pd.Series(
        RNG.normal(0, 0.02, size=len(SYMBOLS)),
        index=pd.Index(SYMBOLS, name="symbol"),
        name="returns",
    )
    return industry, mktcap, returns


# ---------------------------------------------------------------------------
# 1. neutralize 完全剥离 industry+log(mktcap) 线性效应
# ---------------------------------------------------------------------------
def test_neutralize_removes_industry_size_effect():
    """returns 完全由 industry one-hot + log(mktcap) 线性决定（无 alpha）→ 残差≈0。"""
    industry, mktcap, _ = _make_panel()
    # 构造无 alpha 收益：每行业固定系数 + log(mktcap) 系数 + 截距
    industry_coef = {"银行": 0.05, "地产": 0.02, "医药": 0.01, "电子": -0.01, "消费": -0.03}
    log_mkt = np.log(mktcap.to_numpy())
    rets = (
        np.array([industry_coef[v] for v in industry.to_numpy()])
        + 0.003 * (log_mkt - log_mkt.mean())
    )
    returns = _make_indexed(rets, "returns")

    resid = neutralize(returns, industry, mktcap)
    # 残差全部接近 0（abs max < 1e-9）
    assert np.max(np.abs(resid.to_numpy())) < 1e-9
    # index 同 returns
    assert resid.index.equals(returns.index)


# ---------------------------------------------------------------------------
# 2. neutralize 保留已知 alpha
# ---------------------------------------------------------------------------
def test_neutralize_preserves_alpha():
    """returns = industry_effect + size_effect + alpha → 残差≈alpha。

    中性化把 returns 投影到列空间 [行业 one-hot, log(mktcap), 1] 并取残差，
    故 alpha 必须与该列空间正交才能被完整保留。这里用同样的设计矩阵把随机
    alpha 正交化（投影出列空间），保证残差精确恢复 alpha。
    """
    industry, mktcap, _ = _make_panel()
    ind_dummies = pd.get_dummies(industry.to_numpy(), dtype=float)
    log_mkt = np.log(mktcap.to_numpy()).reshape(-1, 1)
    design = np.hstack([ind_dummies, log_mkt, np.ones((len(SYMBOLS), 1))])

    raw = RNG.normal(0, 0.01, size=len(SYMBOLS))
    # 把 raw 投影出列空间，得到与设计矩阵严格正交的 alpha
    beta_proj, *_ = np.linalg.lstsq(design, raw, rcond=None)
    alpha = raw - design @ beta_proj
    alpha = pd.Series(alpha, index=pd.Index(SYMBOLS, name="symbol"), name="alpha")

    industry_coef = {"银行": 0.05, "地产": 0.02, "医药": 0.01, "电子": -0.01, "消费": -0.03}
    size_effect = 0.003 * (log_mkt.ravel() - log_mkt.mean())
    industry_effect = np.array([industry_coef[v] for v in industry.to_numpy()])
    returns = _make_indexed(industry_effect + size_effect + alpha.to_numpy(), "returns")

    resid = neutralize(returns, industry, mktcap)
    np.testing.assert_allclose(resid.to_numpy(), alpha.to_numpy(), atol=1e-9)


# ---------------------------------------------------------------------------
# 3. rank_ic 纯噪声 → |IC| 小
# ---------------------------------------------------------------------------
def test_rank_ic_pure_noise_near_zero():
    """随机因子 + 随机收益（无中性化）→ 单次 |IC| < 0.5（宽松）。"""
    n = 100
    factor = pd.Series(RNG.normal(0, 1, n), index=[f"X{i}" for i in range(n)])
    returns = pd.Series(RNG.normal(0, 0.02, n), index=factor.index)
    ic = rank_ic(factor, returns)
    assert -0.5 < ic < 0.5
    # 多次采样均值应近 0（统计无偏）
    ics = [
        rank_ic(
            pd.Series(RNG.normal(0, 1, n), index=factor.index),
            pd.Series(RNG.normal(0, 0.02, n), index=factor.index),
        )
        for _ in range(200)
    ]
    assert abs(np.mean(ics)) < 0.1


# ---------------------------------------------------------------------------
# 4. rank_ic 强单调因子 → IC 接近 1
# ---------------------------------------------------------------------------
def test_rank_ic_strong_factor_high():
    """因子 = 收益的单调函数 → IC 接近 1（>0.9）。"""
    n = 50
    base = np.arange(n, dtype=float)
    factor = pd.Series(base, index=[f"X{i}" for i in range(n)])
    returns = pd.Series(2.0 * base + 0.001 * RNG.normal(0, 1, n), index=factor.index)
    ic = rank_ic(factor, returns)
    assert ic > 0.9


# ---------------------------------------------------------------------------
# 5. rank_ic 中性化后 IC 反映纯 alpha
# ---------------------------------------------------------------------------
def test_rank_ic_neutralized():
    """因子预测的是去除行业/市值后的残差收益；中性化后 IC 反映纯 alpha。

    构造：returns 含强行业效应（与因子无关），中性化前 IC 被行业噪声稀释；
    中性化后剥离行业效应，IC 升高反映纯 alpha 预测力。两次 IC 不同。
    """
    n = 60
    idx = [f"X{i}" for i in range(n)]
    industries = np.array(["A", "B", "C", "D"] * (n // 4))
    industry = pd.Series(industries, index=idx)
    mktcap = pd.Series(RNG.uniform(1e9, 1e11, n), index=idx)
    # alpha：因子的线性函数（纯 alpha 预测力）
    factor = pd.Series(RNG.normal(0, 1, n), index=idx)
    alpha = 0.02 * factor.to_numpy()
    # 强行业效应（与因子无关，会污染未中性化 IC）
    industry_effect = np.where(
        industries == "A", 0.10,
        np.where(industries == "B", 0.05,
                 np.where(industries == "C", -0.05, -0.10)),
    )
    size_effect = 0.001 * (np.log(mktcap.to_numpy()) - np.log(mktcap.to_numpy()).mean())
    returns = pd.Series(alpha + industry_effect + size_effect, index=idx)

    ic_raw = rank_ic(factor, returns)
    ic_neut = rank_ic(factor, returns, industry=industry, mktcap=mktcap)
    # 中性化前后 IC 明显不同
    assert abs(ic_raw - ic_neut) > 0.01
    # 中性化后 IC 接近 +1（因子单调决定 alpha）
    assert ic_neut > 0.9


# ---------------------------------------------------------------------------
# 6. rank_ic_series 逐截面
# ---------------------------------------------------------------------------
def test_rank_ic_series_per截面():
    """多 trade_date 长格式，逐截面算 IC，返回 Series 长度=trade_date 数。"""
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    n_sym = 30
    rows_f, rows_r = [], []
    for d in dates:
        fvals = RNG.normal(0, 1, n_sym)
        # 因子与收益正相关（IC 应为正）
        rvals = fvals + RNG.normal(0, 0.5, n_sym)
        for j in range(n_sym):
            sym = f"X{j:03d}"
            rows_f.append({"trade_date": d, "symbol": sym, "value": float(fvals[j])})
            rows_r.append({"trade_date": d, "symbol": sym, "value": float(rvals[j])})
    factor_panel = pd.DataFrame(rows_f)
    returns_panel = pd.DataFrame(rows_r)

    ic_series = rank_ic_series(factor_panel, returns_panel)
    assert isinstance(ic_series, pd.Series)
    assert len(ic_series) == len(dates)
    # 每个 IC 为正
    assert (ic_series > 0).all()


# ---------------------------------------------------------------------------
# 7. 样本不足 → nan
# ---------------------------------------------------------------------------
def test_rank_ic_insufficient_sample_nan():
    """截面仅 1 个 symbol → nan。"""
    factor = pd.Series([1.0], index=["X0"])
    returns = pd.Series([0.01], index=["X0"])
    ic = rank_ic(factor, returns)
    assert np.isnan(ic)


# ===========================================================================
# Task B2：IR(Newey-West) + 10 分层 + 新颖性 + 衰减（设计 v0.5 §4.2.3）
# ===========================================================================


# ---------------------------------------------------------------------------
# B2-1. IR + Newey-West t 统计
# ---------------------------------------------------------------------------
def _manual_nw_std(ic: np.ndarray, lag: int) -> float:
    """手算 Newey-West 均值方差对应的 std（对照基准）。

    Var(mean) = (1/n) * [gamma0 + 2*sum_{l=1..lag} (1 - l/(lag+1)) * gamma_l]
    nw_std = sqrt(Var(mean))；gamma_l = (1/n) * sum_{t=l+1..n} (x_t-mean)(x_{t-l}-mean)
    """
    n = len(ic)
    mean = ic.mean()
    centered = ic - mean
    gamma0 = np.dot(centered, centered) / n
    weighted = gamma0
    for l in range(1, lag + 1):
        gamma_l = np.dot(centered[l:], centered[:-l]) / n
        weight = 1.0 - l / (lag + 1)
        weighted += 2.0 * weight * gamma_l
    return float(np.sqrt(weighted / n))


def test_information_ratio_nw():
    """IC 序列带正自相关：IR + NW t；NW std 与手算一致；白噪声 IC 下 NW t≈mean/se。"""
    # AR(1) 正自相关 IC
    n = 60
    ic = np.zeros(n)
    ic[0] = 0.05
    for t in range(1, n):
        ic[t] = 0.7 * ic[t - 1] + RNG.normal(0, 0.02)
    ic_series = pd.Series(ic)

    ir, t_stat = information_ratio(ic_series, lag=5)

    # IR = mean/std（样本 std）
    expected_ir = ic_series.mean() / ic_series.std(ddof=0)
    np.testing.assert_allclose(ir, expected_ir, rtol=1e-9)

    # NW std 与手算一致 → t = mean/nw_std
    nw_std = _manual_nw_std(ic, lag=5)
    np.testing.assert_allclose(t_stat, ic_series.mean() / nw_std, rtol=1e-9)

    # 白噪声 IC：大样本下 NW t ≈ mean/se（gamma_1→0，NW 退化为经典 se）
    noise = pd.Series(RNG.normal(0.0, 0.02, 5000))
    _, t_noise = information_ratio(noise, lag=1)
    se = noise.std(ddof=0) / np.sqrt(len(noise))
    np.testing.assert_allclose(t_noise, noise.mean() / se, rtol=0.05)


# ---------------------------------------------------------------------------
# B2-2. lag 越大吸收更多自相关 → NW std 不同
# ---------------------------------------------------------------------------
def test_ir_lag_effect():
    """强自相关 IC，lag=1 vs lag=5 的 NW std 应明显不同（lag 大者吸收更多自相关）。"""
    n = 80
    ic = np.zeros(n)
    for t in range(1, n):
        ic[t] = 0.8 * ic[t - 1] + RNG.normal(0, 0.01)
    ic_series = pd.Series(ic)

    _, t1 = information_ratio(ic_series, lag=1)
    _, t5 = information_ratio(ic_series, lag=5)

    nw1 = _manual_nw_std(ic, lag=1)
    nw5 = _manual_nw_std(ic, lag=5)
    # lag 不同 → NW std 不同 → t 不同
    assert not np.isclose(nw1, nw5, rtol=1e-3)
    assert not np.isclose(t1, t5, rtol=1e-3)


# ---------------------------------------------------------------------------
# B2-3. 样本不足 → nan
# ---------------------------------------------------------------------------
def test_ir_insufficient_sample_nan():
    """ic_series 长度 < lag+2 → (nan, nan)。"""
    short = pd.Series([0.1, 0.2])  # len=2，lag=1 → 2 < 3
    ir, t_stat = information_ratio(short, lag=1)
    assert np.isnan(ir)
    assert np.isnan(t_stat)


# ---------------------------------------------------------------------------
# B2-3b. ic_series 含 NaN：先 dropna 再算（修 panel 触发的 correctness bug）
# ---------------------------------------------------------------------------
def test_ir_with_nan_drops_then_computes():
    """ic_series 含 NaN → 等价于 dropna 后的 IR/t（手算对照）。

    8-symbol panel 触发的 correctness bug：rank_ic_series 在样本不足截面产 NaN，
    information_ratio 直接对含 NaN 的 Series 算 mean/std → nan 污染 → 返回
    (nan,nan)。修复后应先 dropna，仅在 dropna 后样本过短才返回 (nan,nan)。
    """
    # 完整序列（60 点）的参考 IR/t
    ic = np.array(
        [0.05, 0.07, 0.04, 0.06, 0.08, 0.05, 0.03, 0.04, 0.05, 0.06,
         0.07, 0.05, 0.04, 0.06, 0.05, 0.07, 0.08, 0.05, 0.04, 0.05,
         0.06, 0.07, 0.05, 0.04, 0.05, 0.06, 0.07, 0.05, 0.04, 0.05,
         0.06, 0.07, 0.05, 0.04, 0.05, 0.06, 0.07, 0.05, 0.04, 0.05,
         0.06, 0.07, 0.05, 0.04, 0.05, 0.06, 0.07, 0.05, 0.04, 0.05,
         0.06, 0.07, 0.05, 0.04, 0.05, 0.06, 0.07, 0.05, 0.04, 0.05]
    )
    ic_full = pd.Series(ic)
    ir_ref, t_ref = information_ratio(ic_full, lag=1)

    # 把中间若干点替换为 NaN（模拟某些截面样本不足产 NaN）
    ic_with_nan = ic_full.copy()
    ic_with_nan.iloc[[3, 7, 15, 22, 31]] = np.nan

    # 期望：dropna 后重新算（与手算一致）
    dropped = ic_with_nan.dropna().to_numpy()
    mean_d = dropped.mean()
    std_d = dropped.std(ddof=0)
    expected_ir = mean_d / std_d
    expected_t = mean_d / _manual_nw_std(dropped, lag=1)

    ir, t = information_ratio(ic_with_nan, lag=1)
    np.testing.assert_allclose(ir, expected_ir, rtol=1e-9)
    np.testing.assert_allclose(t, expected_t, rtol=1e-9)
    # 与 full 不等（去掉了若干点）
    assert not np.isclose(ir, ir_ref, rtol=1e-9) or not np.isclose(t, t_ref, rtol=1e-9)


def test_ir_all_nan_returns_nan_pair():
    """ic_series 全 NaN → dropna 后空，返回 (nan,nan)。"""
    all_nan = pd.Series([np.nan, np.nan, np.nan, np.nan])
    ir, t = information_ratio(all_nan, lag=1)
    assert np.isnan(ir)
    assert np.isnan(t)


def test_ir_nan_leaves_too_few_returns_nan_pair():
    """ic_series dropna 后长度 < lag+2 → (nan,nan)。"""
    # 4 个点含 2 个 NaN，dropna 后只剩 2 点，lag=1 要求 ≥3
    short_with_nan = pd.Series([0.1, np.nan, np.nan, 0.2])
    ir, t = information_ratio(short_with_nan, lag=1)
    assert np.isnan(ir)
    assert np.isnan(t)


# ---------------------------------------------------------------------------
# B2-4. 分层单调性
# ---------------------------------------------------------------------------
def test_decile_returns_monotone():
    """因子与 forward_returns 单调正相关 → decile_means 单调增，long_short>0。"""
    n = 200
    base = np.linspace(0, 1, n)
    factor = pd.Series(base + RNG.normal(0, 0.01, n), index=[f"X{i}" for i in range(n)])
    # forward_returns = factor 的单调函数 + 微噪声
    fwd = pd.Series(base + RNG.normal(0, 0.005, n), index=factor.index)

    result = decile_returns(factor, fwd, n_decile=10)
    means = result["decile_means"]
    ls = result["long_short"]

    assert isinstance(means, pd.Series)
    assert list(means.index) == list(range(1, 11))
    # 单调不减（容许轻微抖动，用相邻差全为正的容差判断）
    diffs = np.diff(means.to_numpy())
    assert (diffs > -1e-6).all()
    # 多头减空头 > 0
    assert ls > 0


# ---------------------------------------------------------------------------
# B2-5. qcut 失败兜底（大量重复值）
# ---------------------------------------------------------------------------
def test_decile_returns_qcut_fallback():
    """因子大量重复值（qcut bin 边界非唯一抛错）→ rank 分组兜底，返回 10 组。"""
    # 一半 0、一半 1，qcut 必失败
    n = 200
    factor = pd.Series([0.0] * (n // 2) + [1.0] * (n // 2), index=[f"X{i}" for i in range(n)])
    # 收益按因子分组：0→负，1→正
    fwd = pd.Series(
        [-0.01] * (n // 2) + [0.01] * (n // 2), index=factor.index
    )

    result = decile_returns(factor, fwd, n_decile=10)
    means = result["decile_means"]
    assert len(means) == 10
    assert list(means.index) == list(range(1, 11))
    # 长头减空头 >= 0（兜底应正确区分高低组）
    assert result["long_short"] >= -1e-12


# ---------------------------------------------------------------------------
# B2-6. IC 衰减排序
# ---------------------------------------------------------------------------
def test_ic_decay_sorted():
    """{horizon: ic} → 按 horizon 排序的 Series。"""
    ic_map = {1: 0.10, 5: 0.08, 10: 0.03, 20: 0.01}
    decay = ic_decay(ic_map)
    assert isinstance(decay, pd.Series)
    assert list(decay.index) == [1, 5, 10, 20]
    np.testing.assert_allclose(decay.to_numpy(), [0.10, 0.08, 0.03, 0.01])


# ---------------------------------------------------------------------------
# B2-7. 新颖性高相关被拒
# ---------------------------------------------------------------------------
def test_novelty_high_corr_rejected():
    """factor ≈ known（value_corr > 0.5）→ is_novel=False。"""
    n = 100
    base = RNG.normal(0, 1, n)
    factor = pd.Series(base, index=[f"X{i}" for i in range(n)])
    known = pd.Series(base + RNG.normal(0, 0.01, n), index=factor.index)  # 极高相关

    result = novelty_check(factor, known, threshold=0.5)
    assert result["value_corr"] > 0.5
    assert result["is_novel"] is False
    assert result["return_corr"] is None
    assert result["threshold"] == 0.5


# ---------------------------------------------------------------------------
# B2-8. 新颖性低相关通过
# ---------------------------------------------------------------------------
def test_novelty_low_corr_accepted():
    """factor 与 known 不相关 → is_novel=True。"""
    n = 100
    factor = pd.Series(RNG.normal(0, 1, n), index=[f"X{i}" for i in range(n)])
    known = pd.Series(RNG.normal(0, 1, n), index=factor.index)  # 独立

    result = novelty_check(factor, known, threshold=0.5)
    assert result["value_corr"] < 0.5
    assert result["is_novel"] is True


# ---------------------------------------------------------------------------
# B2-9. 收益预测相关双查
# ---------------------------------------------------------------------------
def test_novelty_return_corr_check():
    """value 低相关但 return 高相关 → is_novel=False（双查任一超阈即拒）。"""
    n = 100
    # factor 值与 known 值不相关
    factor_values = pd.Series(RNG.normal(0, 1, n), index=[f"X{i}" for i in range(n)])
    known_factor_values = pd.Series(RNG.normal(0, 1, n), index=factor_values.index)
    # 但收益预测高度相关
    base_ret = RNG.normal(0, 0.02, n)
    factor_returns = pd.Series(base_ret, index=factor_values.index)
    known_factor_returns = pd.Series(base_ret + RNG.normal(0, 0.0001, n), index=factor_values.index)

    result = novelty_check(
        factor_values,
        known_factor_values,
        factor_returns=factor_returns,
        known_factor_returns=known_factor_returns,
        threshold=0.5,
    )
    assert result["return_corr"] is not None
    assert result["return_corr"] > 0.5
    assert result["is_novel"] is False
