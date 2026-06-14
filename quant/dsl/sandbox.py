"""DSL 沙箱：算子集 = 边界（设计 v0.5 §4.3.3）。

validate 检查表达式只含已注册算子；解析失败或出现未注册算子 → False。
资源限制（超时 / 调用深度）按 YAGNI 暂不强制实现，仅留接口位。
"""
from __future__ import annotations

from quant.dsl.interpreter import _REGISTRY, _parse, DslError

__all__ = ["Sandbox"]


def _collect_call_names(node, acc: set[str]) -> None:
    """递归收集 AST 中所有 call 节点的算子名。"""
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "call":
        acc.add(node[1])
        for arg in node[2]:
            _collect_call_names(arg, acc)
    # field / num 节点无子节点


class Sandbox:
    """算子白名单校验。资源限制预留，M3 不强制。"""

    ALLOWED: frozenset[str] = frozenset(_REGISTRY.keys())

    def validate(self, expr: str) -> bool:
        """表达式只含已注册算子且语法合法 → True；否则 False（不抛）。"""
        try:
            ast = _parse(expr)
        except DslError:
            return False
        names: set[str] = set()
        _collect_call_names(ast, names)
        return names.issubset(self.ALLOWED)
