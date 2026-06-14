from typing import TypeVar

T = TypeVar("T")


class ProviderRegistry:
    """Provider 注册表：按名称登记/获取/查询，同名登记覆盖旧值。"""

    def __init__(self) -> None:
        self._providers: dict[str, T] = {}

    def register(self, name: str, provider: T) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> T:
        return self._providers[name]

    def has(self, name: str) -> bool:
        return name in self._providers
