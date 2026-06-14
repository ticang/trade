"""因子计算的 PIT（point-in-time）沙箱。

设计 v0.5 §4.2.2：FactorContext 注入 decision_time，所有数据访问经
available_at 断言；§4.7.6 防 look-ahead。因子代码只能通过本 ctx 访问数据，
禁止直接 import duckdb/sqlite（靠 ctx 封装 + review 保证）。

数据访问语义：
- field / latest：过滤 available_at <= decision_time（过滤语义，未来行不进入视图）。
- point：单点显式查询；若该行 available_at > decision_time → 抛 LookAheadError，
  命中“按 as_of 查单点且该点未来”场景。
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd


class LookAheadError(Exception):
    """因子访问了 decision_time 之后才可用的数据（look-ahead）。"""


class FactorContext:
    """因子计算的 PIT 沙箱。因子代码只能通过本 ctx 访问数据。

    所有数据访问断言 available_at <= decision_time，违抛 LookAheadError
    （point 单点显式查询）或过滤返回空（field / latest 批量视图）。
    """

    def __init__(
        self,
        decision_time: datetime,
        universe: list[str],
        snapshot_id: str,
        panel: pd.DataFrame,
    ) -> None:
        """panel：长格式 DataFrame，列含 symbol/trade_date/available_at + 各字段。
        ctx 只暴露 available_at <= decision_time 且 symbol ∈ universe 的行。
        """
        self.decision_time = decision_time
        self.universe = universe
        self.snapshot_id = snapshot_id
        self._panel = panel

    # ------------------------------------------------------------------
    # 内部：PIT + universe 过滤
    # ------------------------------------------------------------------
    def _pit_view(self, name: str) -> pd.DataFrame:
        """返回字段 name 的 PIT 安全长格式视图。

        过滤 available_at <= decision_time 且 symbol ∈ universe。
        列：symbol / trade_date / available_at / <name>。
        字段不在 panel → KeyError（不静默）。
        """
        if name not in self._panel.columns:
            raise KeyError(name)
        mask = (
            (self._panel["available_at"] <= self.decision_time)
            & (self._panel["symbol"].isin(self.universe))
        )
        cols = ["symbol", "trade_date", "available_at", name]
        return self._panel.loc[mask, cols].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 批量视图（过滤语义）
    # ------------------------------------------------------------------
    def field(self, name: str) -> pd.DataFrame:
        """返回字段 name 的 PIT 安全视图（长格式）。

        仅含 available_at <= decision_time 且 symbol ∈ universe 的行。
        列：symbol / trade_date / <name>。未来行被过滤，不抛错。
        """
        view = self._pit_view(name)
        return view[["symbol", "trade_date", name]]

    def latest(self, name: str, as_of: datetime | None = None) -> pd.Series:
        """每个 symbol 在 decision_time（或 as_of）时刻该字段最新可得值。

        PIT 安全：过滤 available_at <= 截止时刻，取每 symbol trade_date 最大的行。
        无 PIT 可得行的 symbol 不进入返回（不填 NaN 占位）。返回 index=symbol。
        """
        cutoff = as_of if as_of is not None else self.decision_time
        if name not in self._panel.columns:
            raise KeyError(name)
        mask = (
            (self._panel["available_at"] <= cutoff)
            & (self._panel["symbol"].isin(self.universe))
        )
        sub = self._panel.loc[mask]
        if sub.empty:
            return pd.Series(dtype=float, name=name)
        # 每 symbol 取 trade_date 最大的行
        idx = sub.groupby("symbol")["trade_date"].idxmax()
        latest_rows = sub.loc[idx]
        return latest_rows.set_index("symbol")[name]

    # ------------------------------------------------------------------
    # 单点显式查询（LookAheadError 语义）
    # ------------------------------------------------------------------
    def point(self, symbol: str, field: str, trade_date: date) -> float:
        """单点查询。返回 (symbol, trade_date, field) 行的值。

        - 该行 available_at > decision_time → 抛 LookAheadError（防 look-ahead）。
        - 行不存在（symbol/field/trade_date 组合缺失）→ KeyError。
        - symbol 不在 universe 仍按数据存在性判断（universe 是可选约束，PIT 是硬约束）。
        """
        if field not in self._panel.columns:
            raise KeyError(field)
        mask = (
            (self._panel["symbol"] == symbol)
            & (self._panel["trade_date"] == trade_date)
        )
        matched = self._panel.loc[mask]
        if matched.empty:
            raise KeyError((symbol, field, trade_date))
        available = matched["available_at"].iloc[0]
        if available > self.decision_time:
            raise LookAheadError(
                f"{symbol} {field} @ {trade_date} available_at={available} "
                f"> decision_time={self.decision_time}"
            )
        return float(matched[field].iloc[0])
