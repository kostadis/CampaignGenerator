from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from campaignlib.grounding_config import (
    DEFAULT_CLAIM_CHUNK_CHARS,
    PromotionConfig,
    promotion_config_from_summary_native,
)


def test_missing_promotion_block_has_central_defaults() -> None:
    value = promotion_config_from_summary_native({"extract": {"backend": "claude-code"}})
    assert value.claim_chunk_chars == DEFAULT_CLAIM_CHUNK_CHARS


def test_promotion_block_is_strict_and_does_not_mutate_input() -> None:
    raw = {"promotion": {"claim_chunk_chars": 1234}}
    before = repr(raw)
    assert promotion_config_from_summary_native(raw).claim_chunk_chars == 1234
    assert repr(raw) == before
    with pytest.raises(ValidationError):
        promotion_config_from_summary_native({"promotion": {"chunk_size": 1}})


def test_limits_are_positive() -> None:
    with pytest.raises(ValidationError):
        PromotionConfig(claim_max_tokens=0)


def test_claim_extractor_uses_config_defaults_and_explicit_overrides(tmp_path) -> None:
    from pipelines.summary_native.claims.cli import _resolve_extract_settings

    config = tmp_path / "grounding.yaml"
    config.write_text(
        "selection:\n  backend: openrouter\n  model: vendor/configured\n"
        "summary_native:\n  promotion:\n    claim_max_tokens: 2222\n    claim_chunk_chars: 3333\n"
    )
    unset = SimpleNamespace(backend=None, model=None, max_tokens=None, chunk_chars=None)
    assert _resolve_extract_settings(config, unset) == ("openrouter", "vendor/configured", 2222, 3333)
    explicit = SimpleNamespace(backend="openai", model="flag-model", max_tokens=4444, chunk_chars=5555)
    assert _resolve_extract_settings(config, explicit) == ("openai", "flag-model", 4444, 5555)
