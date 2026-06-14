"""因子评价：rank IC + 行业/log 市值中性化残差（设计 v0.5 §4.2.3）。

IC 衡量因子对去除行业与市值效应后收益的截面排序预测力，隔离 alpha。
- neutralize：对截面收益做 industry（one-hot）+ log(市值) + 截距的最小二乘回归，返回残差。
- rank_ic：截面 Spearman 相关系数；可选先中性化 forward_returns 再算相关。
- rank_ic_series：逐截面（trade_date）算 rank_ic，返回 IC 时序。

向量化：用 numpy np.linalg.lstsq 做最小二乘；scipy.stats.spearmanr 算秩相关。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def neutralize(
    returns: pd.Series,
    industry: pd.Series,
    mktcap: pd.Series,
) -> pd.Series:
    """对截面收益做行业+log(市值) 中性化，返回残差。

    - 对齐 index（symbol），三方 dropna 取交集
    - 设计矩阵 X = [industry one-hot（drop_first=False，全 K 列）, log(mktcap), 1]
      最小二乘 returns ~ X，残差 = returns - X@beta
    - 返回 index 同 returns（仅含对齐后 symbol）
    """
    df = pd.concat(
        [returns.rename("returns"), industry.rename("industry"), mktcap.rename("mktcap")],
        axis=1,
    ).dropna()
    if df.empty:
        return pd.Series(dtype=float, name="residual")

    # 行业 one-hot：pd.get_dummies 生成全 K 列；与截距列并存会共线，
    # np.linalg.lstsq 在秩亏时给出最小范数解，残差仍唯一（投影到列空间不变）
    ind_dummies = pd.get_dummies(df["industry"], dtype=float).to_numpy()
    log_mkt = np.log(df["mktcap"].to_numpy(dtype=float)).reshape(-1, 1)
    ones = np.ones((len(df), 1))
    X = np.hstack([ind_dummies, log_mkt, ones])

    y = df["returns"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return pd.Series(
        resid,
        index=df.index,
        name="residual",
    )


def rank_ic(
    factor: pd.Series,
    forward_returns: pd.Series,
    industry: pd.Series | None = None,
    mktcap: pd.Series | None = None,
) -> float:
    """截面 rank IC（Spearman）。

    - 对齐 index，dropna 取交集；样本 < 2 返回 nan
    - 提供 industry + mktcap：先对 forward_returns 调 neutralize 取残差，
      再算 Spearman(factor, residual_returns)
    - 否则直接 Spearman(factor, forward_returns)
    - 返回 float 相关系数（[-1, 1]）
    """
    pair = pd.concat(
        [factor.rename("factor"), forward_returns.rename("fwd")], axis=1
    ).dropna()
    if len(pair) < 2:
        return float("nan")

    f = pair["factor"]
    r = pair["fwd"]
    if industry is not None and mktcap is not None:
        # 中性化用对齐后的 industry/mktcap
        aligned_ind = industry.reindex(pair.index)
        aligned_mkt = mktcap.reindex(pair.index)
        r = neutralize(r, aligned_ind, aligned_mkt)

    rho, _ = spearmanr(f.to_numpy(), r.to_numpy())
    return float(rho)


def rank_ic_series(
    factor_panel: pd.DataFrame,
    returns_panel: pd.DataFrame,
    industry_panel: pd.DataFrame | None = None,
    mktcap_panel: pd.DataFrame | None = None,
) -> pd.Series:
    """逐截面（trade_date）算 rank_ic，返回 IC 时序 Series（index=trade_date）。

    输入约定：长格式 DataFrame，列 trade_date / symbol / value。
    逐 trade_date 取截面调 rank_ic。
    """

    def _to_series(sub: pd.DataFrame) -> pd.Series:
        return sub.set_index("symbol")["value"]

    # 各 panel 按 trade_date 预分组，避免逐截面 O(n) 掩码扫描
    r_groups = dict(iter(returns_panel.groupby("trade_date")))
    ind_groups = (
        dict(iter(industry_panel.groupby("trade_date")))
        if industry_panel is not None
        else {}
    )
    mkt_groups = (
        dict(iter(mktcap_panel.groupby("trade_date")))
        if mktcap_panel is not None
        else {}
    )

    ics: dict = {}
    for d, f_sub in factor_panel.groupby("trade_date"):
        ic = rank_ic(
            _to_series(f_sub),
            _to_series(r_groups.get(d, pd.DataFrame(columns=["symbol", "value"]))),
            industry=_to_series(ind_groups[d]) if d in ind_groups else None,
            mktcap=_to_series(mkt_groups[d]) if d in mkt_groups else None,
        )
        ics[d] = ic

    return pd.Series(ics, name="rank_ic")


def information_ratio(ic_series: pd.Series, lag: int = 1) -> tuple[float, float]:
    """IR + Newey-West 调整 t 统计（设计 v0.5 §4.2.3）。

    - 先 dropna：NaN 不污染均值/方差估计（小 symbol 数 panel 截面会产 NaN IC）
    - IR = mean(ic) / std(ic)（样本 std，ddof=0）
    - newey_west_t = mean(ic) / nw_std，nw_std 由 HAC 估计均值的方差：
      Var(mean) = (1/n) * [gamma0 + 2*sum_{l=1..lag} (1 - l/(lag+1)) * gamma_l]
      gamma_l = (1/n) * sum_{t=l+1..n} (x_t-mean)(x_{t-l}-mean)
    - lag >= 1；dropna 后样本数 < lag + 2 返回 (nan, nan)
    - 返回 (ir, t_stat)
    """
    s = ic_series.dropna()
    if lag < 1 or len(s) < lag + 2:
        return float("nan"), float("nan")

    ic = s.to_numpy(dtype=float)
    n = len(ic)

    mean = float(ic.mean())
    std = float(ic.std(ddof=0))
    ir = mean / std if std != 0 else float("nan")

    # Newey-West HAC：均值的方差
    centered = ic - mean
    gamma0 = float(np.dot(centered, centered)) / n
    weighted = gamma0
    for l in range(1, lag + 1):
        gamma_l = float(np.dot(centered[l:], centered[:-l])) / n
        weight = 1.0 - l / (lag + 1)
        weighted += 2.0 * weight * gamma_l
    nw_std = float(np.sqrt(weighted / n)) if weighted > 0 else float("nan")
    t_stat = mean / nw_std if nw_std and not np.isnan(nw_std) else float("nan")
    return ir, t_stat


def decile_returns(
    factor: pd.Series, forward_returns: pd.Series, n_decile: int = 10
) -> dict:
    """截面 N 分位分层回测（设计 v0.5 §4.2.3）。

    - 按 factor 排序分 n_decile 组（pd.qcut），算每组 forward_returns 均值
    - 返回 {'decile_means': Series(index=1..n_decile), 'long_short': top-bottom}
    - qcut 因重复值/极端值失败时用 rank-based 分组兜底
    """
    pair = pd.concat(
        [factor.rename("factor"), forward_returns.rename("fwd")], axis=1
    ).dropna()
    n = len(pair)
    if n < n_decile:
        # 样本不足以分组：返回全 nan 的 n_decile 组
        means = pd.Series([float("nan")] * n_decile, index=range(1, n_decile + 1))
        return {"decile_means": means, "long_short": float("nan")}

    f = pair["factor"]
    r = pair["fwd"]

    try:
        groups = pd.qcut(f, n_decile, labels=False, duplicates="raise")
    except ValueError:
        # 兜底：按因子排序后的位置均分 n_decile 桶（np.array_split 保证组数=n_decile），
        # 不依赖值域唯一性，即使大量重复值也能稳定分 10 组
        order = np.argsort(f.to_numpy(dtype=float), kind="stable")
        bucket = np.empty(n, dtype=int)
        for k, idx in enumerate(np.array_split(order, n_decile)):
            bucket[idx] = k
        groups = pd.Series(bucket, index=f.index)

    # qcut 返回 0..k-1，平移到 1..k 作为分位标签
    groups = groups + 1
    means = r.groupby(groups).mean().reindex(range(1, n_decile + 1))

    top = float(means.iloc[-1])
    bottom = float(means.iloc[0])
    long_short = top - bottom if not (np.isnan(top) or np.isnan(bottom)) else float("nan")
    return {"decile_means": means, "long_short": long_short}


def ic_decay(ic_by_horizon: dict[int, float]) -> pd.Series:
    """IC 随 horizon 衰减排序（设计 v0.5 §4.2.3）。

    ic_by_horizon: {horizon_days: ic}。返回按 horizon 升序排序的 Series，
    便于绘图与判断衰减速度。纯排序包装。
    """
    if not ic_by_horizon:
        return pd.Series(dtype=float, name="ic_decay")
    return pd.Series(ic_by_horizon).sort_index().rename("ic_decay")


def novelty_check(
    factor_values: pd.Series,
    known_factor_values: pd.Series,
    factor_returns: pd.Series | None = None,
    known_factor_returns: pd.Series | None = None,
    threshold: float = 0.5,
) -> dict:
    """新颖性双查（设计 v0.5 §4.2.3）。

    - value_corr = |Spearman(factor_values, known_factor_values)|（对齐 index）
    - 提供收益序列时 return_corr = |Spearman(factor_returns, known_factor_returns)|；否则 None
    - is_novel = value_corr < threshold 且 (return_corr is None 或 return_corr < threshold)
    - 任一相关 > threshold → is_novel=False（拒绝为已知因子复述）
    - 返回 {'value_corr', 'return_corr', 'is_novel', 'threshold'}
    """
    pair = pd.concat(
        [factor_values.rename("f"), known_factor_values.rename("k")], axis=1
    ).dropna()
    if len(pair) < 2:
        value_corr = float("nan")
    else:
        rho, _ = spearmanr(pair["f"].to_numpy(), pair["k"].to_numpy())
        value_corr = abs(float(rho))

    return_corr: float | None = None
    if factor_returns is not None and known_factor_returns is not None:
        rp = pd.concat(
            [factor_returns.rename("fr"), known_factor_returns.rename("kr")], axis=1
        ).dropna()
        if len(rp) >= 2:
            rho_r, _ = spearmanr(rp["fr"].to_numpy(), rp["kr"].to_numpy())
            return_corr = abs(float(rho_r))

    def _safe_below(corr: float | None) -> bool:
        return True if corr is None else (not np.isnan(corr) and corr < threshold)

    is_novel = bool(_safe_below(value_corr) and _safe_below(return_corr))
    return {
        "value_corr": value_corr,
        "return_corr": return_corr,
        "is_novel": is_novel,
        "threshold": threshold,
    }
