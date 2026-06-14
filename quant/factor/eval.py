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
