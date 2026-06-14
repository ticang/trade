"""LLM 提示词模板：因子假设生成与裁判评判。

§4.3.2：dsl_expr 只用已注册算子；新颖（避免复述已知因子）。
"""

HYPOTHESIS_SYSTEM = (
    "你是 A 股量化因子研究员。产出可检验、可执行的因子假设："
    "假设需有经济学逻辑，对应的 dsl_expr 只能使用已注册算子"
    "（如 ts_mean/ts_std/rank/ts_rank/zscore/Correlation 等），"
    "不得编造算子；尽量新颖，避免复述已知因子。"
)

JUDGE_SYSTEM = (
    "你是严谨的量化因子评审。基于给定结果客观评判："
    "逻辑是否成立、dsl_expr 是否合法、统计显著性是否达标，给出通过/驳回结论。"
)


def hypothesis_prompt(topic: str, factors_known: list[str], budget: int) -> list[dict]:
    """构造假设生成消息（system + user）。

    user 要求 LLM 产 JSON：{hypothesis, dsl_expr, params, rationale}。
    """
    known = ", ".join(factors_known) if factors_known else "（无）"
    user = (
        f"研究方向：{topic}\n"
        f"已知因子（避免复述）：{known}\n"
        f"本轮假设预算：{budget} 条\n\n"
        "请输出严格 JSON，字段：\n"
        '{"hypothesis": "一句话假设", '
        '"dsl_expr": "仅用已注册算子的表达式", '
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
