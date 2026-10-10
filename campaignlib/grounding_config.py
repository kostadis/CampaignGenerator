"""Central configuration defaults for managed grounding promotion and claims.

The campaign's existing ``grounding.yaml`` remains owned by
``server.grounding_config_shared``.  These strict models define the optional
``summary_native.promotion`` block consumed by both CLI and application code,
so routes never grow a second set of literals.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_CLAIM_CHUNK_CHARS = 24_000
DEFAULT_CLAIM_MAX_TOKENS = 4_096
DEFAULT_MAX_REPORT_BYTES = 8 * 1024 * 1024


class PromotionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim_chunk_chars: int = Field(default=DEFAULT_CLAIM_CHUNK_CHARS, ge=1)
    claim_max_tokens: int = Field(default=DEFAULT_CLAIM_MAX_TOKENS, ge=1)
    max_report_bytes: int = Field(default=DEFAULT_MAX_REPORT_BYTES, ge=1)
    relevant_note_paths: tuple[str, ...] = ()
    rule_versions: tuple[str, ...] = ("grounding-claims/1", "grounding-bundle-signoff/2")


def promotion_config_from_summary_native(raw: Any) -> PromotionConfig:
    """Return the optional strict promotion block without mutating config.

    ``raw`` may be the parsed ``summary_native`` mapping or ``None``. Unknown
    fields inside the promotion block refuse through Pydantic. Other existing
    summary-native keys are deliberately ignored here and remain owned by their
    established schema.
    """

    if raw is None:
        return PromotionConfig()
    if not isinstance(raw, dict):
        raise ValueError("summary_native config must be a mapping")
    block = raw.get("promotion")
    if block is None:
        return PromotionConfig()
    return PromotionConfig.model_validate(block)
