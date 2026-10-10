from types import SimpleNamespace
import sys

import pytest

from pipelines.summary_native.concurrency import resolve_concurrency


def test_explicit_wins_over_registry(monkeypatch):
    monkeypatch.setitem(sys.modules, "dgxlib", SimpleNamespace(resolve_model_config=lambda _: SimpleNamespace(max_concurrency=8)))
    assert resolve_concurrency(explicit=3, backend="dgx", model="m").value == 3


def test_registry_value_and_absence_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "dgxlib", SimpleNamespace(resolve_model_config=lambda _: SimpleNamespace(max_concurrency=8)))
    declared = resolve_concurrency(explicit=None, backend="dgx", model="m")
    assert (declared.value, declared.source, declared.model, declared.declared_max) == (8, "dgxlib", "m", 8)
    monkeypatch.setitem(sys.modules, "dgxlib", SimpleNamespace(resolve_model_config=lambda _: SimpleNamespace(max_concurrency=None)))
    resolution = resolve_concurrency(explicit=None, backend="dgx", model="m")
    assert (resolution.value, resolution.source) == (6, "fallback")


def test_invalid_registry_value_refuses(monkeypatch):
    monkeypatch.setitem(sys.modules, "dgxlib", SimpleNamespace(resolve_model_config=lambda _: SimpleNamespace(max_concurrency=0)))
    with pytest.raises(ValueError, match="max_concurrency"):
        resolve_concurrency(explicit=None, backend="dgx", model="m")


def test_non_dgx_and_missing_model_use_the_stable_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "dgxlib", SimpleNamespace(resolve_model_config=lambda _: SimpleNamespace(max_concurrency=99)))
    resolution = resolve_concurrency(explicit=None, backend="anthropic", model="m")
    assert (resolution.value, resolution.source, resolution.model) == (6, "fallback", "m")
