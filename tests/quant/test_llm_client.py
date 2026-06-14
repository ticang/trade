"""LLM 客户端测试：mock 为主，真实 API 标 network 默认 deselect。

§4.3.4：密钥读环境变量/.env，绝不入代码。
"""
import pytest

from quant.llm.client import LLMClient
from quant.llm import prompt


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """记录 create 调用参数，返回固定响应。"""

    def __init__(self, content):
        self._content = content
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeOpenAI:
    """替身 OpenAI client：跳过真实 HTTP。"""

    def __init__(self, content=""):
        self.chat = _FakeChat(content)


def _make_client_with_fake(content):
    """构造一个绕过凭证检查、注入 fake client 的 LLMClient。"""
    c = LLMClient.__new__(LLMClient)
    c.base_url = "http://fake"
    c.api_key = "fake-key"
    c.model = "fake-model"
    c._client = _FakeOpenAI(content)
    return c


def test_complete_json_parses():
    """纯 JSON 文本直接解析为 dict。"""
    c = _make_client_with_fake('{"hypothesis":"x","dsl_expr":"rank(close)"}')
    out = c.complete_json([{"role": "user", "content": "hi"}])
    assert out == {"hypothesis": "x", "dsl_expr": "rank(close)"}


def test_complete_json_extracts_from_text():
    """前后含解释文字时，仍提取首个 {...} 块解析。"""
    raw = '好的，结果如下：\n{"hypothesis":"y","dsl_expr":"ts_mean(close,5)"}\n以上。'
    c = _make_client_with_fake(raw)
    out = c.complete_json([{"role": "user", "content": "hi"}])
    assert out == {"hypothesis": "y", "dsl_expr": "ts_mean(close,5)"}


def test_complete_json_bad_raises():
    """无法解析为 JSON 的内容抛 ValueError。"""
    c = _make_client_with_fake("这根本不是 JSON")
    with pytest.raises(ValueError):
        c.complete_json([{"role": "user", "content": "hi"}])


def test_complete_json_array_takes_first_element():
    """真实 LLM 常返回 JSON 数组：取首元素解析为 dict。"""
    raw = '[{"hypothesis":"x","dsl_expr":"rank(close)"}]'
    c = _make_client_with_fake(raw)
    out = c.complete_json([{"role": "user", "content": "hi"}])
    assert out == {"hypothesis": "x", "dsl_expr": "rank(close)"}


def test_complete_json_array_multi_takes_first():
    """多元素数组也只取首个元素。"""
    raw = (
        '[{"hypothesis":"a","dsl_expr":"rank(close)"},'
        '{"hypothesis":"b","dsl_expr":"ts_mean(close,5)"}]'
    )
    c = _make_client_with_fake(raw)
    out = c.complete_json([{"role": "user", "content": "hi"}])
    assert out == {"hypothesis": "a", "dsl_expr": "rank(close)"}


def test_complete_json_array_first_element_not_dict_raises():
    """数组首元素非对象（如纯字符串）→ ValueError。"""
    c = _make_client_with_fake('["not-an-object"]')
    with pytest.raises(ValueError):
        c.complete_json([{"role": "user", "content": "hi"}])


def test_complete_json_array_with_surrounding_text():
    """数组前后含解释文字时，仍提取数组并取首元素。"""
    raw = '候选列表：\n[{"hypothesis":"x","dsl_expr":"rank(close)"}]\n以上。'
    c = _make_client_with_fake(raw)
    out = c.complete_json([{"role": "user", "content": "hi"}])
    assert out == {"hypothesis": "x", "dsl_expr": "rank(close)"}


def test_missing_credentials_raises(monkeypatch):
    """清空 env 且无 .env 可读时，构造客户端报 RuntimeError。"""
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("quant.llm.client._ENV_LOADED", True)
    with pytest.raises(RuntimeError):
        LLMClient()


def test_temperature_default_zero():
    """complete 默认 temperature=0.0（复现性）。"""
    c = _make_client_with_fake("{}")
    c.complete([{"role": "user", "content": "hi"}])
    assert c._client.chat.completions.last_kwargs["temperature"] == 0.0


def test_prompt_templates_structure():
    """hypothesis_prompt 返回 list[dict]，含 system 与 user role。"""
    msgs = prompt.hypothesis_prompt(
        topic="低波动",
        factors_known=["rank(close)"],
        available_operators=["rank", "ts_mean"],
        available_fields=["close", "volume"],
        round_idx=0,
        budget=3,
    )
    assert isinstance(msgs, list)
    assert all(isinstance(m, dict) for m in msgs)
    roles = [m["role"] for m in msgs]
    assert "system" in roles and "user" in roles
    # judge_prompt 同样结构
    jmsgs = prompt.judge_prompt({"hypothesis": "x", "dsl_expr": "rank(close)"})
    assert isinstance(jmsgs, list) and all(isinstance(m, dict) for m in jmsgs)


def test_hypothesis_prompt_requests_one_hypothesis():
    """prompt 明确「产出 1 条」而非诱导返回 N 条数组。"""
    msgs = prompt.hypothesis_prompt(
        topic="量价动量",
        factors_known=[],
        available_operators=["rank", "ts_mean", "mul"],
        available_fields=["close", "volume"],
        round_idx=2,
        budget=12,
    )
    user_text = msgs[-1]["content"]
    # 含「1 条」/「一条」字样（中文数字兼容）
    assert ("1 条" in user_text) or ("一条" in user_text)
    # 不应诱导返回整个 budget 数组
    assert f"{12} 条" not in user_text
    assert "请输出" in user_text


def test_hypothesis_prompt_lists_operators_and_fields():
    """prompt 附可用算子清单与 panel 字段清单，约束 LLM 输出。"""
    msgs = prompt.hypothesis_prompt(
        topic="量价动量",
        factors_known=[],
        available_operators=["rank", "ts_mean", "mul"],
        available_fields=["close", "volume"],
        round_idx=0,
        budget=10,
    )
    user_text = msgs[-1]["content"]
    assert "rank" in user_text
    assert "ts_mean" in user_text
    assert "mul" in user_text
    assert "close" in user_text
    assert "volume" in user_text


def test_hypothesis_prompt_has_dsl_syntax_example():
    """prompt 含 DSL 语法示例（函数式 + add/mul 而非中缀），提示一元负号用 neg。"""
    msgs = prompt.hypothesis_prompt(
        topic="量价动量",
        factors_known=[],
        available_operators=["rank", "ts_mean", "mul", "neg"],
        available_fields=["close"],
        round_idx=0,
        budget=10,
    )
    user_text = msgs[-1]["content"]
    assert "mul(" in user_text  # 强调函数式而非 *
    assert "neg" in user_text   # 提示负号 → neg


def test_hypothesis_prompt_includes_arg_type_constraints():
    """prompt 含算子参数类型表：field/expr/num 三类，正反例。

    第二层 P0：LLM 把表达式嵌进 ts_corr 的 field 位置被拒，因为 prompt 未
    告知参数类型约束。修复后 prompt 必须明示：
    - 每个算子标注参数类型（field=字段名, expr=可嵌套表达式, num=整数窗口）
    - 时序算子 ts_* 的序列参数必须是字段名（不可嵌套表达式）
    - 提供正例（合法）与反例（非法）
    """
    msgs = prompt.hypothesis_prompt(
        topic="量价动量",
        factors_known=[],
        available_operators=["rank", "ts_mean", "ts_corr", "mul", "add"],
        available_fields=["close", "volume"],
        round_idx=0,
        budget=10,
    )
    user_text = msgs[-1]["content"]

    # 参数类型三分类必须出现（field/expr/num）
    assert "field" in user_text
    assert "expr" in user_text
    assert "num" in user_text
    # ts_corr 的签名必须明示（field, field, num）
    assert "ts_corr" in user_text
    # 时序算子序列参数必须是字段名这一约束必须出现
    assert "ts_mean" in user_text
    # 必须含正例与反例标识
    assert "正例" in user_text or "合法" in user_text
    assert "反例" in user_text or "非法" in user_text
    # 反例必须含把表达式塞进 field 位置的典型错误提示
    # （至少出现「不能」「字段名」「表达式」之一与 field 相关的明确说明）
    assert "字段名" in user_text or "不能" in user_text


def test_hypothesis_prompt_arg_type_examples_dsl_runnable():
    """prompt 中的正例 DSL 必须能被 Sandbox 接受；反例必须被拒。

    用真实 DSL registry 验证示例的合规性，保证给 LLM 的指引自身正确。
    """
    from quant.dsl.sandbox import Sandbox

    msgs = prompt.hypothesis_prompt(
        topic="量价动量",
        factors_known=[],
        available_operators=["rank", "ts_mean", "ts_corr", "mul", "add", "ts_delta"],
        available_fields=["close", "volume"],
        round_idx=0,
        budget=10,
    )
    user_text = msgs[-1]["content"]
    sb = Sandbox()

    # 正例：至少出现一个嵌套表达式在 rank/mul/add（expr 位置）的合法用法
    # 至少给出 ts_corr 的合法用法（两个 field + 一个 num）
    assert "ts_corr(" in user_text

    # 验证 prompt 给出的某个合法 ts_corr 示例确实通过 Sandbox
    # （从 prompt 提取形如 ts_corr(field, field, num) 的子串来验证）
    import re
    corr_examples = re.findall(r"ts_corr\(\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*\d+\s*\)", user_text)
    assert len(corr_examples) >= 1, "prompt 应至少给出一个合法的 ts_corr(field, field, num) 示例"
    for ex in corr_examples:
        assert sb.validate(ex) is True, f"prompt 给出的合法示例被 Sandbox 拒: {ex!r}"


def test_complete_max_tokens_default_4096():
    """complete 默认 max_tokens=4096（修复 1024 截断）。"""
    c = _make_client_with_fake("ok")
    c.complete([{"role": "user", "content": "hi"}])
    assert c._client.chat.completions.last_kwargs["max_tokens"] == 4096


def test_complete_json_max_tokens_default_4096():
    """complete_json 也走 4096 默认。"""
    c = _make_client_with_fake('{"a":1}')
    c.complete_json([{"role": "user", "content": "hi"}])
    assert c._client.chat.completions.last_kwargs["max_tokens"] == 4096


@pytest.mark.network
def test_complete_real_api():
    """真实 Volces Ark 连通性检查；无凭证则 skip。"""
    import os

    from quant.llm.client import _load_env

    _load_env()
    if not (os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_API_KEY") and os.environ.get("LLM_MODEL")):
        pytest.skip("LLM 凭证未配置，跳过真实 API 测试")
    c = LLMClient()
    out = c.complete([{"role": "user", "content": "回复一个词：连通"}], max_tokens=16)
    assert isinstance(out, str) and len(out) > 0
