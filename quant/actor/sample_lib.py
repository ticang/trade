"""主体样本库（设计 v0.5 §4.9.1 / §4.9.2）。

聚合多主体样本，提供按 kind 过滤、偏差声明汇总、小样本降级候选识别。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from quant.actor.model import Actor, ActorKind, ActorTrade


@dataclass
class SampleLibrary:
    """主体样本集合。"""

    actors: dict[str, Actor] = field(default_factory=dict)

    def add(self, actor: Actor) -> None:
        """注册主体（id 唯一，后入覆盖）。"""
        self.actors[actor.id] = actor

    def by_kind(self, kind: ActorKind) -> list[Actor]:
        """按 kind 过滤。"""
        return [a for a in self.actors.values() if a.kind == kind]

    def all_trades(self, kind: ActorKind | None = None) -> list[ActorTrade]:
        """汇总成交；kind=None 时返回全部。"""
        actors = (
            list(self.actors.values())
            if kind is None
            else self.by_kind(kind)
        )
        out: list[ActorTrade] = []
        for a in actors:
            out.extend(a.trades)
        return out

    def bias_declarations(self) -> dict[str, str]:
        """汇总非空 bias_note：{actor_id: bias_note}。"""
        return {a.id: a.bias_note for a in self.actors.values() if a.bias_note}

    def small_sample_actors(self, min_trades: int = 30) -> list[str]:
        """trades 数 < min_trades 的主体 id（自身小样本降级标注候选）。"""
        return [
            a.id for a in self.actors.values() if len(a.trades) < min_trades
        ]
