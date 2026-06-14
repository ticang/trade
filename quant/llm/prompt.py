"""LLM 提示词模板：因子假设生成与裁判评判。

§4.3.2：dsl_expr 只用已注册算子；新颖（避免复述已知因子）。

协议：每轮请求**恰好 1 条**新假设（不返回数组）。附可用算子清单 + panel
字段清单 + DSL 语法示例，把 LLM 输出约束在沙箱边界内。
"""

HYPOTHESIS_SYSTEM = (
    "你是 A 股量化因子研究员。产出可检验、可执行的因子假设："
    "假设需有经济学逻辑，对应的 dsl_expr 只能使用本消息给出的可用算子清单，"
    "字段只能取自可用字段清单；不得编造算子或字段；"
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

    协议要点（修 P0）：
    - **逐轮只产 1 条新假设**（不要返回数组）。budget 是总轮数，每轮调用一次。
    - 附可用算子清单 + panel 字段清单，约束 LLM 输出在沙箱边界内。
    - DSL 语法示例：函数式 mul/add/sub/div，一元负号用 neg(...)。
    """
    known = ", ".join(factors_known) if factors_known else "（无）"
    ops_list = ", ".join(available_operators) if available_operators else "（无）"
    fields_list = ", ".join(available_fields) if available_fields else "（无）"
    user = (
        f"研究方向：{topic}\n"
        f"已知因子（避免复述）：{known}\n"
        f"第 {round_idx} 轮（共 {budget} 轮）\n\n"
        f"可用算子清单：{ops_list}\n"
        f"可用字段清单：{fields_list}\n\n"
        "本轮请产出 **1 条** 新假设（不要返回数组、不要多条）。"
        "dsl_expr 语法：算子调用 func(arg, ...)；"
        "算术必须用函数式 add/sub/mul/div，**不要**用中缀 + - * /；"
        "一元负号用 neg(...)，例如 rank(neg(ts_mean(close, 20)))；"
        "乘法示例：mul(rank(close), rank(ts_delta(close, 5)))。\n"
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
