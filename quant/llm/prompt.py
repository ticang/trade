"""LLM 提示词模板：因子假设生成与裁判评判。

§4.3.2：dsl_expr 只用已注册算子；新颖（避免复述已知因子）。

协议：每轮请求**恰好 1 条**新假设（不返回数组）。附可用算子清单 + panel
字段清单 + DSL 语法示例 + 算子参数类型表，把 LLM 输出约束在沙箱边界内。
"""

from quant.dsl.interpreter import _REGISTRY

# 参数类型中文释义：与 interpreter._REGISTRY 中 arg_types 一一对应
_ARG_TYPE_DESC = {
    "field": "field（字段名，如 close/volume，不可为表达式）",
    "expr": "expr（可嵌套表达式，如 rank(close) 或 add(a,b)）",
    "num": "num（整数窗口或常量，如 5）",
}


def _build_arg_type_table(available_operators: list[str]) -> str:
    """从 _REGISTRY 提取可用算子的签名表，明示每个参数的类型约束。

    格式：op_name(arg_type1, arg_type2, ...)；标注 field/expr/num。
    仅展示 available_operators 中存在的算子，按字母序输出。
    """
    lines: list[str] = []
    for op in sorted(set(available_operators)):
        entry = _REGISTRY.get(op)
        if entry is None:
            continue
        _func, _arity, arg_types = entry
        types_desc = ", ".join(_ARG_TYPE_DESC.get(t, t) for t in arg_types)
        lines.append(f"- {op}({types_desc})")
    return "\n".join(lines)


HYPOTHESIS_SYSTEM = (
    "你是 A 股量化因子研究员。产出可检验、可执行的因子假设："
    "假设需有经济学逻辑，对应的 dsl_expr 只能使用本消息给出的可用算子清单，"
    "字段只能取自可用字段清单；不得编造算子或字段；"
    "严格遵守每个算子的参数类型约束（field/expr/num）；"
    "尽量新颖，避免复述已知因子。"
)

JUDGE_SYSTEM = (
    "你是严谨的量化因子评审。基于给定结果客观评判："
    "逻辑是否成立、dsl_expr 是否合法、统计显著性是否达标，给出通过/驳回结论。"
)


def hypothesis_prompt(
    topic: str,
    factors_known: list[str],
    available_operators: list[str],
    available_fields: list[str],
    round_idx: int,
    budget: int,
) -> list[dict]:
    """构造假设生成消息（system + user）。

    协议要点：
    - **逐轮只产 1 条新假设**（不要返回数组）。budget 是总轮数，每轮调用一次。
    - 附可用算子清单 + panel 字段清单，约束 LLM 输出在沙箱边界内。
    - DSL 语法示例：函数式 mul/add/sub/div，一元负号用 neg(...)。
    - **算子参数类型表**（修第二层 P0）：每个算子标注 field/expr/num，
      时序算子 ts_* 的序列参数必须是字段名（不可嵌套表达式）；组合时用
      rank/zscore 包裹或用 add/mul 算术连接两个独立时序因子。
    """
    known = ", ".join(factors_known) if factors_known else "（无）"
    ops_list = ", ".join(available_operators) if available_operators else "（无）"
    fields_list = ", ".join(available_fields) if available_fields else "（无）"
    arg_type_table = _build_arg_type_table(available_operators)

    user = (
        f"研究方向：{topic}\n"
        f"已知因子（避免复述）：{known}\n"
        f"第 {round_idx} 轮（共 {budget} 轮）\n\n"
        f"可用算子清单：{ops_list}\n"
        f"可用字段清单：{fields_list}\n\n"
        "算子参数类型约束（field=字段名字符串；expr=可嵌套表达式；num=整数常量）：\n"
        f"{arg_type_table}\n\n"
        "关键规则：**时序算子（ts_mean/ts_corr/ts_delta/ts_rank 等 ts_*）"
        "的 field 参数必须是字段名（如 close、volume），不能是嵌套表达式**。"
        "要组合多个时序因子，用 rank/zscore 包裹，或用 add/mul/sub/div 算术连接。\n\n"
        "正例（合法）：\n"
        "- rank(ts_delta(close, 5))：rank 的 expr 参数接收嵌套时序表达式\n"
        "- mul(rank(ts_delta(close, 5)), rank(ts_delta(volume, 5)))：两个独立时序因子相乘\n"
        "- ts_corr(close, volume, 20)：ts_corr 两个 field 参数都是字段名，第三参数 num\n"
        "- add(rank(close), zscore(ts_mean(volume, 10)))：算术 + 截面变换组合\n\n"
        "反例（非法，会被 Sandbox 拒）：\n"
        "- ts_corr(ts_delta(close,1), ts_delta(volume,1), 20)：ts_corr 的 field 位置"
        "不能放 ts_delta(...) 表达式\n"
        "- ts_mean(rank(close), 5)：ts_mean 的 field 位置不能放 rank(close) 表达式\n"
        "- ts_delta(mul(close, volume), 5)：ts_delta 的 field 位置不能放算术表达式\n\n"
        "本轮请产出 **1 条** 新假设（不要返回数组、不要多条）。"
        "dsl_expr 语法：算子调用 func(arg, ...)；"
        "算术必须用函数式 add/sub/mul/div，**不要**用中缀 + - * /；"
        "一元负号用 neg(...)，例如 rank(neg(ts_mean(close, 20)))。\n"
        "字段名只能取自上方字段清单。\n\n"
        "请输出严格 JSON（单个对象，不要包在数组里），字段：\n"
        '{"hypothesis": "一句话假设", '
        '"dsl_expr": "仅用可用算子和字段的表达式", '
        '"params": {"窗口或参数名": 值}, '
        '"rationale": "经济学/逻辑依据"}\n'
        "不要输出 JSON 之外的文字。"
    )
    return [
        {"role": "system", "content": HYPOTHESIS_SYSTEM},
        {"role": "user", "content": user},
    ]


def judge_prompt(result_json: dict) -> list[dict]:
    """构造裁判消息（system + user）。result_json 为待评判结果。"""
    import json as _json

    user = (
        "请评审以下因子结果，输出严格 JSON：\n"
        '{"verdict": "pass|reject", "reasons": ["..."], "score": 0-10}\n\n'
        f"待评审结果：\n{_json.dumps(result_json, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]
