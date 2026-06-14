"""因子挖掘 Tester：双门入库门禁（设计 v0.5 §4.2.4 / §11 M3）。

防过拟合：统计显著（BH-FDR p<alpha）**且** 经济显著（IC/IR/分层多空年化）才入库。
BH-FDR 分母用预登记假设预算数（hypothesis_budget），非实际假设数，防 optional stopping。

复用 M1 eval：
- rank_ic_series：逐截面 rank IC（可选行业/市值中性化）
- information_ratio：IR + Newey-West t
- novelty_check：与已知因子的新颖性
- decile_returns：最后一截面分层多空，年化近似

BH-FDR 简化：单假设用 budget 放大 bh_fdr_p = p_value * hypothesis_budget（封顶 1），
模拟"分母用预算数"；完整多假设排序留后续。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant.factor.eval import (
    decile_returns,
    information_ratio,
    novelty_check,
    rank_ic_series,
)


@dataclass
class TestConfig:
    """门禁阈值（设计 v0.5 §4.2.4）。"""

    bh_fdr_alpha: float = 0.05          # BH-FDR 显著水平
    min_ic: float = 0.03                # 经济显著 IC 下限
    min_ir: float = 0.5                 # 经济显著 IR 下限
    min_long_short_annual: float = 0.05 # 分层多空扣费后年化下限
    novelty_threshold: float = 0.5      # 新颖性相关阈值
    trading_days: int = 252             # 年化天数


@dataclass
class TestResult:
    """单因子全门禁结果。"""

    passed: bool
    ic: float
    ir: float
    bh_fdr_p: float
    novelty_is_novel: bool
    long_short_annual: float
    reasons: list[str] = field(default_factory=list)  # 拒因码


class Tester:
    """全门禁测试器：IC / IR / BH-FDR / 新颖性 / 经济显著 五门。"""

    def __init__(self, config: TestConfig | None = None):
        self.config = config or TestConfig()

    def test(
        self,
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        industry_panel: pd.DataFrame | None = None,
        mktcap_panel: pd.DataFrame | None = None,
        known_factor_panels: list | None = None,
        hypothesis_budget: int = 10,
        p_value: float | None = None,
    ) -> TestResult:
        """全门禁测试，逐项不过追加 reason。

        factor_panel / returns_panel：长格式（trade_date / symbol / value）。
        p_value：单假设 p（如因子 IC 的 t 检验 p）。
        hypothesis_budget：BH-FDR 分母（预登记假设预算数，防 optional stopping）。
        """
        cfg = self.config
        reasons: list[str] = []

        # IC 时序（复用 M1 eval，逐截面 rank IC）
        ic_series = rank_ic_series(
            factor_panel, returns_panel, industry_panel, mktcap_panel
        )
        ic = float(ic_series.mean())
        ir, _t = information_ratio(ic_series)

        # 新颖性：与任一已知因子高相关即不 novel（取最后一截面做代表）
        novelty_is_novel = True
        if known_factor_panels:
            last_date = factor_panel["trade_date"].iloc[-1]
            f_last = _slice(factor_panel, last_date)
            for known in known_factor_panels:
                k_last = _slice(known, last_date)
                res = novelty_check(f_last, k_last, threshold=cfg.novelty_threshold)
                if not res["is_novel"]:
                    novelty_is_novel = False
                    break

        # 分层多空年化：最后一截面 long_short × trading_days（简化年化）
        last_date = factor_panel["trade_date"].iloc[-1]
        f_last = _slice(factor_panel, last_date)
        r_last = _slice(returns_panel, last_date)
        ls = decile_returns(f_last, r_last)["long_short"]
        long_short_annual = float(ls) * cfg.trading_days if ls == ls else float("nan")

        # BH-FDR：分母用预算数（bh_fdr_p = p * budget，封顶 1）
        p = 0.0 if p_value is None else float(p_value)
        bh_fdr_p = min(1.0, p * hypothesis_budget)

        # 五门判定
        if ic != ic or ic < cfg.min_ic:
            reasons.append("ic_below_min")
        if ir != ir or ir < cfg.min_ir:
            reasons.append("ir_below_min")
        if bh_fdr_p >= cfg.bh_fdr_alpha:
            reasons.append("bh_fdr_fail")
        if not novelty_is_novel:
            reasons.append("novelty_fail")
        if long_short_annual != long_short_annual or long_short_annual < cfg.min_long_short_annual:
            reasons.append("long_short_annual_below_min")

        passed = len(reasons) == 0
        return TestResult(
            passed=passed,
            ic=ic,
            ir=ir,
            bh_fdr_p=bh_fdr_p,
            novelty_is_novel=novelty_is_novel,
            long_short_annual=long_short_annual,
            reasons=reasons,
        )


def _slice(panel: pd.DataFrame, trade_date) -> pd.Series:
    """取某截面长格式 panel 的 symbol->value Series。"""
    sub = panel[panel["trade_date"] == trade_date]
    return sub.set_index("symbol")["value"]
