"""主体行为学习 AI 归纳（设计 v0.5 §4.9.3 路径2）。

LLM 读主体高胜率 trades 样本 → 归纳高胜率条件 → 候选 DSL 因子/规则。

与路径1（stat_profile，可解释统计画像）互补：路径2 直接由 LLM 输出可执行
的假设表达式。产出受沙箱算子白名单约束，并对已知因子做去重（避免复述）。

复用 M3：LLMClient.complete_json / Sandbox.validate / novelty_check 思路。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from quant.actor.model import Actor
from quant.dsl.sandbox import Sandbox
from quant.llm.client import LLMClient

__all__ = ["InductResult", "AIInduct"]


# AI 归纳系统提示：聚焦主体行为 → 高胜率条件 → 因子假设
_INDUCT_SYSTEM = (
    "你是 A 股量化主体行为研究员。给定某交易主体的成交样本与统计摘要，"
    "归纳其高胜率的市场条件，并产出可检验的因子假设：dsl_expr 只能使用"
    "本消息给出的可用算子清单；不得编造算子；尽量新颖，避免复述已知因子。"
)


@dataclass
class InductResult:
    """AI 归纳结果。"""

    candidates: list[dict] = field(default_factory=list)  # {hypothesis, dsl_expr, rationale}
    rejected: list[dict] = field(default_factory=list)  # {dsl_expr, reason}（未注册算子/重复）
    n_samples: int = 0


def _normalize_expr(expr: str) -> str:
    """归一化 DSL 表达式：去空白、统一小写算子名，便于查重比对。"""
    # 去所有空白
    compact = re.sub(r"\s+", "", expr)
    # 算子名小写（字段名保持原样，但查重场景下字段名相同亦视为重复）
    return compact.lower()


def _build_actor_summary(actor: Actor) -> str:
    """构造主体摘要：kind + 交易笔数 + 胜率 + 板块分布 + 样本 symbol。

    喂给 LLM 帮助其归纳高胜率条件；信息量受控避免过载。
    """
    trades = actor.trades
    n = len(trades)
    closed = [t for t in trades if t.realized_pnl != 0.0]
    wins = [t for t in closed if t.realized_pnl > 0]
    win_rate = f"{len(wins) / len(closed):.2%}" if closed else "n/a"

    # 板块分布（context['sector']，缺失归 unknown）
    sector_count: dict[str, int] = {}
    for t in trades:
        sec = t.context.get("sector", "unknown")
        sector_count[sec] = sector_count.get(sec, 0) + 1
    sector_str = ", ".join(f"{k}:{v}" for k, v in sorted(sector_count.items()))

    # 样本 symbol（最多前 5 个，避免 prompt 过长）
    sample_symbols = sorted({t.symbol for t in trades})[:5]
    return (
        f"主体类型：{actor.kind.value}\n"
        f"交易笔数：{n}\n"
        f"胜率：{win_rate}\n"
        f"板块分布：{sector_str or 'n/a'}\n"
        f"样本 symbol：{', '.join(sample_symbols) if sample_symbols else 'n/a'}"
    )


def _build_prompt(
    actor_summary: str,
    known_exprs: list[str],
    available_operators: list[str],
    round_idx: int,
    budget: int,
) -> list[dict]:
    """构造归纳消息（system + user）。

    协议：逐轮只产 1 条新假设；附可用算子清单 + 已知因子清单（DSL 表达式），
    约束 LLM 输出在沙箱边界内并避免复述已知因子。
    """
    ops_list = ", ".join(available_operators) if available_operators else "（无）"
    known_list = ", ".join(known_exprs) if known_exprs else "（无）"
    user = (
        f"主体行为摘要：\n{actor_summary}\n\n"
        f"第 {round_idx} 轮（共 {budget} 轮）\n\n"
        f"可用算子清单：{ops_list}\n"
        f"已知因子（避免复述）：{known_list}\n\n"
        "请基于主体样本归纳高胜率条件，产出 **1 条** 新假设（不要返回数组）。"
        "dsl_expr 语法：算子调用 func(arg, ...)；算术用 add/sub/mul/div，"
        "一元负号用 neg(...)，时序算子（ts_*）的序列参数必须是字段名。\n\n"
        "请输出严格 JSON（单个对象），字段：\n"
        '{"hypothesis": "一句话高胜率条件假设", '
        '"dsl_expr": "仅用可用算子的表达式", '
        '"rationale": "为何该条件对该主体高胜率"}\n'
        "不要输出 JSON 之外的文字。"
    )
    return [
        {"role": "system", "content": _INDUCT_SYSTEM},
        {"role": "user", "content": user},
    ]


class AIInduct:
    """AI 归纳：LLM 读主体样本 → 候选 DSL 因子/规则。"""

    def __init__(self, llm: LLMClient, sandbox: Sandbox | None = None):
        self.llm = llm
        self.sandbox = sandbox or Sandbox()

    def induct(
        self,
        actor: Actor,
        known_factor_panels: list | None = None,
        budget: int = 5,
    ) -> InductResult:
        """LLM 读主体高胜率样本 → 归纳高胜率条件 → 候选 DSL 因子/规则。

        - 构造 prompt：actor kind/统计摘要/样本摘要 + 可用算子 + 已知因子清单
        - llm.complete_json（逐轮 1 条，循环 budget 次，复用 M3 模式）
        - Sandbox.validate(dsl_expr)：不合法 → rejected(reason='dsl_invalid')
        - novelty_check vs known_factor_panels（DSL 表达式清单）：重复 → rejected(reason='novelty_fail')
        - 合法+新颖 → candidates

        known_factor_panels 此处为已知 DSL 表达式字符串清单（ai_induct 阶段无 panel 可评估候选）。
        """
        candidates: list[dict] = []
        rejected: list[dict] = []

        known_exprs = list(known_factor_panels or [])
        known_norm = {_normalize_expr(e) for e in known_exprs}
        available_operators = sorted(self.sandbox.ALLOWED)
        actor_summary = _build_actor_summary(actor)

        for i in range(budget):
            messages = _build_prompt(
                actor_summary, known_exprs, available_operators, i, budget
            )
            try:
                item = self.llm.complete_json(messages)
            except (ValueError, TypeError):
                rejected.append({"dsl_expr": "", "reason": "llm_parse_error"})
                continue

            hypothesis = str(item.get("hypothesis", "")).strip()
            dsl_expr = str(item.get("dsl_expr", "")).strip()
            rationale = str(item.get("rationale", "")).strip()

            # 门一：算子白名单
            if not self.sandbox.validate(dsl_expr):
                rejected.append({"dsl_expr": dsl_expr, "reason": "dsl_invalid"})
                continue

            # 门二：已知因子查重（归一化 DSL 字符串比对）
            if _normalize_expr(dsl_expr) in known_norm:
                rejected.append({"dsl_expr": dsl_expr, "reason": "novelty_fail"})
                continue

            candidates.append(
                {
                    "hypothesis": hypothesis,
                    "dsl_expr": dsl_expr,
                    "rationale": rationale,
                }
            )

        return InductResult(
            candidates=candidates,
            rejected=rejected,
            n_samples=budget,
        )
