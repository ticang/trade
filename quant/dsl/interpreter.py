"""DSL 解释器：tokenizer / parser / evaluator（设计 v0.5 §4.3.3）。

LLM 产算子表达式字符串 → 解释器解析并执行（内部受信任 pandas/numpy 代码）。
PIT 安全、缺失值传播、向量化在解释器层统一保障；算子集 = 沙箱边界。

AST 三种节点：
- ("field", name)  —— 数据列名（求值为 df[name] Series；作为 field 参数则传字段名字符串）
- ("num", value)   —— 数值常量
- ("call", fname, [args])  —— 算子调用，args 为 AST 列表
"""
from __future__ import annotations

import re
from typing import Callable, List, Sequence, Tuple, Union

import pandas as pd

from quant.dsl import operators as ops

__all__ = ["DslError", "evaluate", "Sandbox"]

# AST 节点类型别名
Ast = Union[Tuple[str, str], Tuple[str, float], Tuple[str, str, List["Ast"]]]

# arg_types 取值：'field'（传字段名字符串）/ 'expr'（传已求值 Series）/ 'num'（传数值）
OpEntry = Tuple[Callable, int, Sequence[str]]

# 算子注册表：name -> (func, arity, arg_types)
_REGISTRY: dict[str, OpEntry] = {
    # 时序（per symbol）
    "ts_mean": (ops.ts_mean, 2, ["field", "num"]),
    "delay": (ops.delay, 2, ["field", "num"]),
    "ts_delta": (ops.ts_delta, 2, ["field", "num"]),
    "ts_rank": (ops.ts_rank, 2, ["field", "num"]),
    "ts_max": (ops.ts_max, 2, ["field", "num"]),
    "ts_std": (ops.ts_std, 2, ["field", "num"]),
    "ts_corr": (ops.ts_corr, 3, ["field", "field", "num"]),
    "decay_linear": (ops.decay_linear, 2, ["field", "num"]),
    # 横截面（per trade_date）
    "rank": (ops.rank, 1, ["expr"]),
    "zscore": (ops.zscore, 1, ["expr"]),
    "quantile": (ops.quantile, 2, ["expr", "num"]),
    "winsorize": (ops.winsorize, 2, ["expr", "num"]),
    "scale": (ops.scale, 1, ["expr"]),
    "group_neutral": (ops.group_neutral, 2, ["expr", "field"]),
    # 算术（无 df，签名特殊）
    "signed_power": (ops.signed_power, 2, ["expr", "num"]),
    "add": (ops.add, 2, ["expr", "expr"]),
    "sub": (ops.sub, 2, ["expr", "expr"]),
    "mul": (ops.mul, 2, ["expr", "expr"]),
    "div": (ops.div, 2, ["expr", "expr"]),
}

# signed_power / add / sub / mul / div 不接收 df（签名仅含 series/常量），调用时不传 df
_NO_DF_OPS = frozenset({"signed_power", "add", "sub", "mul", "div"})


class DslError(Exception):
    """DSL 解析 / 求值过程中的所有错误。"""


# ===========================================================================
# tokenizer
# ===========================================================================
_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<num>\d+\.\d+|\d+)        # 整数 / 浮点
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)  # 标识符（字段名 / 算子名）
      | (?P<punc>[(),])              # 括号 / 逗号
    )
    """,
    re.VERBOSE,
)


def _tokenize(s: str) -> List[Tuple[str, str]]:
    """拆分为 token 序列；非法字符 → DslError。"""
    tokens: List[Tuple[str, str]] = []
    pos = 0
    n = len(s)
    while pos < n:
        # 跳过前导空白
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n:
            break
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise DslError(f"非法字符位置 {pos}: {s[pos:]!r}")
        if m.group("num") is not None:
            tokens.append(("num", m.group("num")))
        elif m.group("name") is not None:
            tokens.append(("name", m.group("name")))
        else:
            tokens.append(("punc", m.group("punc")))
        pos = m.end()
    return tokens


# ===========================================================================
# parser（递归下降）
# ===========================================================================
class _Parser:
    def __init__(self, tokens: List[Tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> Tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self) -> Tuple[str, str]:
        if self.i >= len(self.tokens):
            raise DslError("意外的表达式结尾")
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse(self) -> Ast:
        node = self._parse_atom()
        if self.i != len(self.tokens):
            raise DslError(f"尾部多余 token: {self.tokens[self.i:]}")
        return node

    def _parse_atom(self) -> Ast:
        tok = self._peek()
        if tok is None:
            raise DslError("意外的表达式结尾")
        kind, val = tok
        if kind == "num":
            self._next()
            num_val: float = float(val) if "." in val else int(val)
            return ("num", num_val)
        if kind == "name":
            self._next()
            # 后跟 '(' 视为算子调用，否则视为字段名
            nxt = self._peek()
            if nxt is not None and nxt == ("punc", "("):
                self._next()  # 消费 '('
                args = self._parse_args()
                return ("call", val, args)
            return ("field", val)
        raise DslError(f"意外 token: {tok}")

    def _parse_args(self) -> List[Ast]:
        args: List[Ast] = []
        nxt = self._peek()
        # 空参数列表（DSL 无此合法算子，统一交给 arity 校验拒绝）
        if nxt == ("punc", ")"):
            self._next()
            return args
        while True:
            args.append(self._parse_atom())
            nxt = self._peek()
            if nxt == ("punc", ","):
                self._next()
                continue
            if nxt == ("punc", ")"):
                self._next()
                return args
            raise DslError(f"参数列表中期待 ',' 或 ')', 实际 {nxt}")


def _parse(s: str) -> Ast:
    return _Parser(_tokenize(s)).parse()


# ===========================================================================
# evaluator
# ===========================================================================
def _eval(node: Ast, df: pd.DataFrame) -> Union[pd.Series, float, int]:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "field":
        name = node[1]
        if name not in df.columns:
            raise DslError(f"未知字段: {name}")
        return df[name]
    if kind == "call":
        return _eval_call(node, df)
    raise DslError(f"未知 AST 节点: {node}")


def _eval_call(node: Ast, df: pd.DataFrame) -> pd.Series:
    _, fname, arg_nodes = node  # type: ignore[misc]
    if fname not in _REGISTRY:
        raise DslError(f"未知算子: {fname}")
    func, arity, arg_types = _REGISTRY[fname]
    if len(arg_nodes) != arity:
        raise DslError(
            f"算子 {fname} 参数数不符: 期望 {arity}, 实际 {len(arg_nodes)}"
        )

    # 按位置拼装调用参数：field→字段名字符串，expr→已求值 Series，num→数值
    call_args: List[object] = []
    for arg_node, arg_type in zip(arg_nodes, arg_types):
        if arg_type == "field":
            if arg_node[0] != "field":
                raise DslError(
                    f"算子 {fname} 的 field 参数必须是字段名, 实际 {arg_node}"
                )
            field_name = arg_node[1]
            if field_name not in df.columns:
                raise DslError(f"未知字段: {field_name}")
            call_args.append(field_name)
        elif arg_type == "expr":
            evaluated = _eval(arg_node, df)
            if not isinstance(evaluated, pd.Series):
                raise DslError(
                    f"算子 {fname} 的 expr 参数必须求值为 Series, 实际 {type(evaluated)}"
                )
            call_args.append(evaluated)
        elif arg_type == "num":
            if arg_node[0] != "num":
                raise DslError(
                    f"算子 {fname} 的 num 参数必须是数值常量, 实际 {arg_node}"
                )
            call_args.append(arg_node[1])
        else:  # pragma: no cover - 注册表已限定取值
            raise DslError(f"未知 arg_type: {arg_type}")

    # signed_power 等无 df 算子不传 df
    if fname in _NO_DF_OPS:
        result = func(*call_args)
    else:
        result = func(df, *call_args)

    if not isinstance(result, pd.Series):
        raise DslError(f"算子 {fname} 未返回 Series")
    return result


def evaluate(expr: str, df: pd.DataFrame) -> pd.Series:
    """解析并求值 DSL 表达式，返回与 df 对齐的因子 Series。"""
    ast = _parse(expr)
    result = _eval(ast, df)
    if not isinstance(result, pd.Series):
        # 顶层为 num 节点等非 Series 情形
        raise DslError(f"表达式最终未求值为 Series: {expr}")
    return result
