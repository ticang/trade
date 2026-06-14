import pytest

from quant.providers.registry import ProviderRegistry


class _Stub:
    """简单 provider 占位。"""


def test_register_and_get_roundtrip():
    reg = ProviderRegistry()
    stub = _Stub()
    reg.register("calendar", stub)
    assert reg.get("calendar") is stub


def test_get_unregistered_raises_keyerror():
    reg = ProviderRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_has_true_when_registered():
    reg = ProviderRegistry()
    reg.register("calendar", _Stub())
    assert reg.has("calendar") is True


def test_has_false_when_absent():
    reg = ProviderRegistry()
    assert reg.has("calendar") is False


def test_register_overwrites_same_name():
    reg = ProviderRegistry()
    first = _Stub()
    second = _Stub()
    reg.register("calendar", first)
    reg.register("calendar", second)
    assert reg.get("calendar") is second
