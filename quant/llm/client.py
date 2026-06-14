"""LLM 客户端：火山 Volces Ark（OpenAI 兼容），承载 DeepSeek。

§4.3.4：密钥读环境变量/.env，绝不入代码。
"""
import json
import os
import re
from pathlib import Path

from openai import OpenAI

# .env 是否已加载，避免重复解析
_ENV_LOADED = False


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
        max_tokens: int = 1024,
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
        return resp.choices[0].message.content

    def complete_json(self, messages: list[dict], **kw) -> dict:
        """complete 后解析 JSON。容错：提取首个 {...} 块；失败抛 ValueError。"""
        content = self.complete(messages, **kw)
        text = content.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = match.group(0) if match else text
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 输出无法解析为 JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"LLM JSON 非对象: {type(obj).__name__}")
        return obj
