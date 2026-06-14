import logging

import pytest

from quant.logging_setup import setup_logging
from quant.secrets import EnvSecretManager, SecretManager


def test_env_secret_manager_returns_set_value(monkeypatch):
    monkeypatch.setenv("API_KEY", "abc123")
    assert EnvSecretManager().get("API_KEY") == "abc123"


def test_env_secret_manager_unset_raises_keyerror(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(KeyError):
        EnvSecretManager().get("MISSING_KEY")


def test_secret_manager_is_protocol():
    # SecretManager 作为 Protocol 仅用于类型标注，不应被实例化
    assert SecretManager.__class__.__name__ in {"_ProtocolMeta", "type"}


def test_setup_logging_adds_handler_and_sets_level():
    root = logging.getLogger()
    # 清空既有 handler 以便观察 setup 行为
    saved_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        setup_logging("WARNING")
        assert len(root.handlers) == 1
        assert root.level == logging.WARNING
        fmt = root.handlers[0].formatter
        assert fmt is not None
        assert "%(name)s" in fmt._fmt
    finally:
        root.handlers = saved_handlers


def test_setup_logging_idempotent():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        setup_logging("INFO")
        count_after_first = len(root.handlers)
        setup_logging("DEBUG")
        assert len(root.handlers) == count_after_first  # 不重复加 handler
        assert root.level == logging.DEBUG  # level 仍可更新
    finally:
        root.handlers = saved_handlers
