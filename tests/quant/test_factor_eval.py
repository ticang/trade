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

from quant.factor.eval import neutralize, rank_ic, rank_ic_series


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
