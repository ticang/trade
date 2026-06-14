"""主体行为学习 ML 模仿（设计 v0.5 §4.9.3 路径3）。

线性回归学习"主体在何种特征下能赚取 PnL"：
- 标签 = trade.realized_pnl（连续值，非"是否盈利"二元；避免把连续收益强行
  二值化造成信息损失，也避免用"是否盈利"标签隐含的阈值前视）
- 特征由调用方提供的 feature_fn 给出，**PIT（point-in-time）约束由调用方
  在 feature_fn 中保证**：特征只能用 trade 当时可观测的字段，严禁使用
  realized_pnl 自身或任何未来信息作为特征（否则构成前视）
- OOS 切分按 actor 切（Leave-One-Actor-Out，LOAO）：某 actor 全期作 OOS 时
  不参与训练，避免同 actor 交易样本横跨训练/OOS 造成泄露；这比按时间切更
  严格地评估"行为模式跨主体可迁移性"

训练：线性回归（np.linalg.lstsq），逐 LOAO 折拟合，coefs 取各折均值。
OOS IC：留出 actor 的预测 PnL 与实际 PnL 的 Spearman rank 相关，多折取均值。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import spearmanr

from quant.actor.model import Actor

__all__ = ["MLResult", "MLImitate"]


@dataclass
class MLResult:
    """ML 模仿结果。

    Attributes:
        coefs: 特征权重（各 LOAO 折的均值）
        intercept: 截距（各 LOAO 折的均值）
        oos_ic: Leave-One-Actor-Out 聚合 OOS IC（Spearman rank corr）
        held_out_actors: 每 LOAO 折被留出的 actor id（共 N 折）
    """

    coefs: np.ndarray
    intercept: float
    oos_ic: float
    held_out_actors: list[str] = field(default_factory=list)


def _spearman_rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank 相关：对 x、y 求秩后做 Pearson 相关。

    返回 [-1, 1]；样本 < 2 或秩全相同时 scipy 返回 nan，归一为 0.0（无信息）。
    与 quant/factor/eval.py 一致使用 scipy.stats.spearmanr。
    """
    if len(x) < 2 or len(y) < 2:
        return 0.0
    rho, _ = spearmanr(x, y)
    if np.isnan(rho):
        # 一侧常数序列 → 无方向信息
        return 0.0
    return float(rho)


class MLImitate:
    """Leave-One-Actor-Out ML 模仿。

    标签=realized_pnl（连续）；特征 PIT 约束由调用方 feature_fn 保证；
    OOS 按 actor 切（LOAO），不按时间切。
    """

    def fit_loao(self, actors: list[Actor], feature_fn) -> MLResult:
        """Leave-One-Actor-Out：每次留出 1 个 actor 全期作 OOS，其余 actor 训练。

        Args:
            actors: 主体列表（≥2 才有 LOAO 意义；<2 时退化为零折）
            feature_fn: callable(actor_trade) -> np.ndarray，
                特征向量（PIT 约束由调用方保证：不得使用 realized_pnl 或
                未来信息作为特征）

        Returns:
            MLResult：coefs/intercept 为各折均值；oos_ic 为各折 OOS rank IC
            的均值；held_out_actors 列出每折被留出的 actor id。
        """
        if len(actors) < 2:
            # 单一 actor 无 LOAO 意义；返回空结果（coefs 维度由首折决定无可能）
            # 此处不抛异常：调用方传边界数据应能拿到可识别结果
            raise ValueError(
                "LOAO 需要 ≥2 个 actor，当前 %d" % len(actors)
            )

        coefs_list: list[np.ndarray] = []
        intercept_list: list[float] = []
        ic_list: list[float] = []
        held: list[str] = []

        for hold_idx in range(len(actors)):
            held_actor = actors[hold_idx]
            train_actors = [a for i, a in enumerate(actors) if i != hold_idx]

            # 构造训练矩阵
            X_train, y_train = self._build_matrix(train_actors, feature_fn)
            if len(X_train) == 0:
                continue

            # 加截距列：[1, *features]
            X_with_bias = np.hstack(
                [np.ones((X_train.shape[0], 1)), X_train]
            )
            # 最小二乘解：返回 (coefs_with_bias, ...)
            coefs_bias, *_ = np.linalg.lstsq(
                X_with_bias, y_train, rcond=None
            )
            intercept = float(coefs_bias[0])
            coefs = coefs_bias[1:]
            coefs_list.append(coefs)
            intercept_list.append(intercept)
            held.append(held_actor.id)

            # OOS：留出 actor 的 trades 预测 vs 实际
            X_oos, y_oos = self._build_matrix([held_actor], feature_fn)
            if len(X_oos) == 0:
                continue
            pred_oos = X_oos @ coefs + intercept
            ic = _spearman_rank_corr(pred_oos, y_oos)
            ic_list.append(ic)

        # coefs 取各折均值
        mean_coefs = (
            np.mean(np.vstack(coefs_list), axis=0)
            if coefs_list
            else np.array([])
        )
        mean_intercept = float(np.mean(intercept_list)) if intercept_list else 0.0
        mean_ic = float(np.mean(ic_list)) if ic_list else 0.0

        return MLResult(
            coefs=mean_coefs,
            intercept=mean_intercept,
            oos_ic=mean_ic,
            held_out_actors=held,
        )

    def predict(
        self,
        coefs: np.ndarray,
        intercept: float,
        features: np.ndarray,
    ) -> np.ndarray:
        """线性预测 PnL：features @ coefs + intercept。

        Args:
            coefs: 特征权重（与 features 末维同长）
            intercept: 截距
            features: 2D 数组 (n_samples, n_features)

        Returns:
            1D 预测值数组 (n_samples,)
        """
        features = np.asarray(features, dtype=float)
        return features @ np.asarray(coefs, dtype=float) + float(intercept)

    @staticmethod
    def _build_matrix(
        actors: list[Actor], feature_fn
    ) -> tuple[np.ndarray, np.ndarray]:
        """从 actor 列表构造 (X, y)：X=特征矩阵，y=realized_pnl。

        标签 = trade.realized_pnl（连续值，非二元）。
        """
        rows_X: list[np.ndarray] = []
        rows_y: list[float] = []
        for actor in actors:
            for trade in actor.trades:
                feat = np.asarray(feature_fn(trade), dtype=float)
                rows_X.append(feat.reshape(-1))
                rows_y.append(float(trade.realized_pnl))
        if not rows_X:
            return np.empty((0, 0)), np.empty((0,))
        X = np.vstack(rows_X)
        y = np.array(rows_y, dtype=float)
        return X, y
