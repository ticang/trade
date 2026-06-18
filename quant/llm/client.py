"""LLM 客户端：火山 Volces Ark（OpenAI 兼容），承载 DeepSeek。

§4.3.4：密钥读环境变量/.env，绝不入代码。
"""
import json
import os
from pathlib import Path

from openai import OpenAI

# .env 是否已加载，避免重复解析
_ENV_LOADED = False


def _extract_first_json(text: str) -> str:
    """从文字中提取首个配平的 JSON 片段（对象或数组）。

    扫描首个 ``{`` 或 ``[`` 作为起点，按括号配平确定终点；忽略字符串字面量
    与转义字符内的括号。找不到起点则原样返回（交由上层 json.loads 报错）。
    """
    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start < 0:
        return text

    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # 未配平：返回从起点到末尾，交由上层报错
    return text[start:]


def _load_env() -> None:
    """从仓库根 .env 填充 os.environ（仅设置缺失项）。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


class LLMClient:
    """OpenAI 兼容 chat completions 客户端。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        _load_env()
        self.base_url = base_url or os.environ.get("LLM_BASE_URL")
        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        self.model = model or os.environ.get("LLM_MODEL")
        if not (self.base_url and self.api_key and self.model):
            raise RuntimeError(
                "LLM credentials missing: set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL in .env"
            )
        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kw,
    ) -> str:
        """OpenAI 兼容 chat.completions.create，返回 choices[0].message.content。"""
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kw,
        )
        for retry_tokens in (max(max_tokens * 4, 256), max(max_tokens * 8, 512)):
            choice = resp.choices[0]
            content = choice.message.content or ""
            if content:
                return content
            if getattr(choice, "finish_reason", None) != "length":
                return content
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=retry_tokens,
                **kw,
            )
        return resp.choices[0].message.content or ""

    def complete_json(self, messages: list[dict], **kw) -> dict:
        """complete 后解析 JSON。容错：提取首个完整 JSON 值并归一为 dict。

        支持三种真实 LLM 产出形态：
        - 纯对象 ``{...}``：直接解析
        - 文字夹对象 ``前文 {...} 后文``：提取首个配平的 ``{...}``
        - JSON 数组 ``[{...}, ...]``：取首个元素（非对象 → ValueError）
        解析失败抛 ValueError。
        """
        text = self.complete(messages, **kw).strip()
        candidate = _extract_first_json(text)
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 输出无法解析为 JSON: {e}") from e
        # 数组归一：取首元素
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        if not isinstance(obj, dict):
            raise ValueError(f"LLM JSON 非对象: {type(obj).__name__}")
        return obj
