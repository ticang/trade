import os
from typing import Protocol


class SecretManager(Protocol):
    def get(self, key: str) -> str: ...


class EnvSecretManager:
    """从环境变量取密钥；未设置抛 KeyError。keyring/age fallback 留 M2。"""

    def get(self, key: str) -> str:
        val = os.environ.get(key)
        if val is None:
            raise KeyError(f"secret not set: {key}")
        return val
