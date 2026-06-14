"""组合优化器：标量化 QP + 主板 100 股整数化 + gap（§4.4.3）。

目标：max α'w − λ·TE² − γ·turnover
  - α = 信号 strength（多头方向），TE 为相对基准的平方跟踪误差
  - turnover 为相对当前持仓的 L1 换手
约束：满仓、单票上限、换手硬上限。
连续 QP 解 → lot 整数化启发式（当前默认主板 100 股，按 α 降序贪心，违反约束降一档）
→ gap = |obj_int − obj_cont| / |obj_cont| 量化整数化损失，超阈值告警。
"""
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np

from quant.strategy.signal import Signal


@dataclass
class OptimizerConfig:
    """优化器参数（§4.4.3）。"""

    lam: float = 1.0            # 风险厌恶 λ（TE² 惩罚）
    gamma: float = 0.5           # 换手惩罚 γ
    max_single: float = 0.10     # 单票权重上限
    max_turnover: float = 0.30   # 换手硬上限
    lot_sizes: dict = field(default_factory=lambda: {"default": 100})  # symbol->lot（默认100）
    gap_threshold: float = 0.02  # gap 告警阈值（目标函数相对差）


@dataclass
class OptimizeResult:
    """优化结果。"""

    weights: dict[str, float]             # 整数化后 symbol->权重
    continuous_weights: dict[str, float]  # 连续解 symbol->权重
    gap: float
    gap_warning: bool                     # gap 超阈值 或 QP 不可行回退
    objective_continuous: float
    objective_integer: float
    note: str = ""                        # 回退/告警原因


class PortfolioOptimizer:
    """基于 cvxpy 的组合优化器。"""

    def __init__(self, config: OptimizerConfig | None = None):
        self.config = config or OptimizerConfig()

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------
    def optimize(
        self,
        signals: list[Signal],
        current_weights: dict[str, float] | None = None,
        benchmark: dict[str, float] | None = None,
        total_capital: float = 1_000_000.0,
    ) -> OptimizeResult:
        """求解组合优化问题。

        signals: list[Signal]，alpha 取 strength。
        current_weights / benchmark: symbol->权重，缺失补 0。
        total_capital: 总资金，用于确定整数化粒度。
        """
        symbols = [s.symbol for s in signals]
        alpha = np.array([float(s.strength) for s in signals], dtype=float)
        n = len(symbols)

        has_current = bool(current_weights)
        current_weights = current_weights or {}
        benchmark = benchmark or {}

        w_cur = np.array([float(current_weights.get(s, 0.0)) for s in symbols], dtype=float)
        w_bench = np.array([float(benchmark.get(s, 0.0)) for s in symbols], dtype=float)

        # 连续 QP 解（无当前持仓视为冷启动，换手硬上限不约束）
        w_cont, feasible = self._solve_continuous(alpha, w_cur, w_bench, has_current)

        if not feasible:
            # 不可行回退：等权连续解 + 告警
            w_cont = np.ones(n) / n
            w_int = w_cont.copy()
            obj_cont = self._objective(alpha, w_cont, w_cur, w_bench)
            obj_int = obj_cont
            return OptimizeResult(
                weights={symbols[i]: float(w_int[i]) for i in range(n)},
                continuous_weights={symbols[i]: float(w_cont[i]) for i in range(n)},
                gap=0.0,
                gap_warning=True,
                objective_continuous=float(obj_cont),
                objective_integer=float(obj_int),
                note="qp infeasible, fallback to equal weight",
            )

        # 当前主板 lot 整数化
        w_int = self._integerize(alpha, w_cont, symbols, total_capital)

        obj_cont = self._objective(alpha, w_cont, w_cur, w_bench)
        obj_int = self._objective(alpha, w_int, w_cur, w_bench)
        gap = self._compute_gap(obj_cont, obj_int)

        return OptimizeResult(
            weights={symbols[i]: float(w_int[i]) for i in range(n)},
            continuous_weights={symbols[i]: float(w_cont[i]) for i in range(n)},
            gap=float(gap),
            gap_warning=bool(gap > self.config.gap_threshold),
            objective_continuous=float(obj_cont),
            objective_integer=float(obj_int),
        )

    # ------------------------------------------------------------------
    # 连续 QP 求解
    # ------------------------------------------------------------------
    def _solve_continuous(
        self,
        alpha: np.ndarray,
        w_cur: np.ndarray,
        w_bench: np.ndarray,
        has_current: bool,
    ) -> tuple[np.ndarray, bool]:
        """求连续 QP：max α'w − λ·TE² − γ·turnover。

        返回 (连续解, 是否可行)。has_current 为 False（冷启动）时不施加换手硬上限。
        """
        n = len(alpha)
        w = cp.Variable(n)

        te = cp.sum_squares(w - w_bench)
        turnover = cp.norm1(w - w_cur)
        objective = cp.Maximize(alpha @ w - self.config.lam * te - self.config.gamma * turnover)

        constraints = [
            cp.sum(w) == 1,
            w >= 0,
            w <= self.config.max_single,
        ]
        if has_current:
            constraints.append(cp.norm1(w - w_cur) <= self.config.max_turnover)

        problem = cp.Problem(objective, constraints)
        self._solve(problem)

        if problem.status not in ("optimal", "optimal_inaccurate"):
            return np.zeros(n), False
        return np.asarray(w.value, dtype=float), True

    def _solve(self, problem: cp.Problem) -> None:
        """按可用性选择求解器（OSQP 优先，回退默认）。"""
        for solver in ("OSQP", "ECOS", "CLARABEL", "SCS"):
            if solver in cp.installed_solvers():
                try:
                    problem.solve(solver=solver)
                    if problem.status in ("optimal", "optimal_inaccurate"):
                        return
                except Exception:
                    continue
        problem.solve()

    # ------------------------------------------------------------------
    # 主板 lot 整数化（§4.4.3 M1.5 简化）
    # ------------------------------------------------------------------
    def _integerize(
        self,
        alpha: np.ndarray,
        w_cont: np.ndarray,
        symbols: list[str],
        total_capital: float,
    ) -> np.ndarray:
        """连续权重整数化为 lot 单位权重，归一至 sum=1。

        n_lots = floor(capital_per_symbol / (lot * ref_price))，ref_price 取 1。
        按 alpha 降序贪心填充，违反 max_single 降一档 lot。
        """
        n = len(symbols)
        per_symbol = total_capital / n
        # 每个 symbol 的 lot 单位数（ref_price=1 简化）
        n_lots_per_symbol = []
        for sym in symbols:
            lot = self._lot_size(sym)
            n_lots_per_symbol.append(max(1, int(per_symbol // lot)))
        # 用最小粒度统一量化（保证整数 lot 可在 symbol 间调和配额）
        n_lots = min(n_lots_per_symbol)
        n_lots = max(n_lots, n)  # 至少能分配到每个 symbol

        # 各 symbol 容许的最大 lot 数（受 max_single 约束）
        max_lot = max(1, int(self.config.max_single * n_lots))

        # 初步整数化
        lots = np.array([min(int(round(w_cont[i] * n_lots)), max_lot) for i in range(n)], dtype=int)

        # 归一：使 sum(lots) == n_lots，按 alpha 降序贪心
        order_desc = np.argsort(-alpha)  # alpha 降序
        order_asc = np.argsort(alpha)    # alpha 升序（先削低 alpha）

        # 超额：按 alpha 升序削减
        while lots.sum() > n_lots:
            trimmed = False
            for i in order_asc:
                if lots[i] > 0:
                    lots[i] -= 1
                    trimmed = True
                    break
            if not trimmed:
                break

        # 不足：按 alpha 降序补加（受 max_lot 约束）
        while lots.sum() < n_lots:
            added = False
            for i in order_desc:
                if lots[i] < max_lot:
                    lots[i] += 1
                    added = True
                    break
            if not added:
                break

        return lots.astype(float) / n_lots

    def _lot_size(self, symbol: str) -> int:
        if symbol in self.config.lot_sizes:
            return int(self.config.lot_sizes[symbol])
        return int(self.config.lot_sizes.get("default", 100))

    # ------------------------------------------------------------------
    # 目标函数与 gap
    # ------------------------------------------------------------------
    def _objective(
        self, alpha: np.ndarray, w: np.ndarray, w_cur: np.ndarray, w_bench: np.ndarray
    ) -> float:
        te = float(np.sum((w - w_bench) ** 2))
        turnover = float(np.sum(np.abs(w - w_cur)))
        return float(alpha @ w) - self.config.lam * te - self.config.gamma * turnover

    @staticmethod
    def _compute_gap(obj_cont: float, obj_int: float) -> float:
        """gap = |obj_int − obj_cont| / |obj_cont|，obj_cont≈0 时用绝对差。"""
        denom = abs(obj_cont)
        if denom < 1e-12:
            return abs(obj_int - obj_cont)
        return abs(obj_int - obj_cont) / denom
