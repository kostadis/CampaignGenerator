"""NPC dossiers configuration model (spec 032, T048): the shape of ``<config>/npc_dossiers.yaml``.

A dedicated, strict (``extra="forbid"``) file. It holds only the NPC dossiers service's own
knobs. ``summaries_dir``, ``out_root``, ``registry``, ``canon_file`` and the chapter range stay
in ``grounding.yaml summary_native``, the one place they are spelled (Principle XII).

Every default is imported from ``schema.py``, the one place they are declared.

The model lives here, in the engine layer, rather than in ``server/``: the CLI
(``cli.py``) and the web service (``server/npc_dossiers_config.py``) must read this file
through one definition, and ``tests/test_layering.py`` forbids the engine importing
``server``. The server imports it from here, like it does ``schema``.

Model and backend: ``draft.backend`` / ``draft.model`` are the defaults for ``npc-draft``; the
optional top-level ``selection`` is the web service's override (feature 003) and beats them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from campaignlib.selection import Backend, ModelSelection
from campaignlib.util import atomic_write_text
from pipelines.summary_native.schema import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_DRAFT_BACKEND,
    DEFAULT_DRAFT_MODE,
    DEFAULT_DRAFT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NPC_ROOT,
    DEFAULT_RECENT_CHAPTERS,
    DEFAULT_RECURRING_MIN,
)

NPC_DOSSIERS_CONFIG_FILENAME = "npc_dossiers.yaml"


class NpcDraftBlock(BaseModel):
    """The ``draft:`` block. Strict: an unknown key (``endpoint`` for one) refuses."""

    model_config = ConfigDict(extra="forbid")

    backend: Backend = DEFAULT_DRAFT_BACKEND  # type: ignore[assignment]
    model: str = DEFAULT_DRAFT_MODEL
    mode: Literal["chunked", "one-shot"] = DEFAULT_DRAFT_MODE  # type: ignore[assignment]
    chunk_chars: int = Field(default=DEFAULT_CHUNK_CHARS, ge=1)

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be blank")
        return v.strip()

    def effective_model(self) -> str | None:
        """The model that belongs to ``backend``, or ``None`` for "let the command decide".

        The schema model belongs to the schema backend. A file that names another backend
        and no model of its own must not send a Spark model id to that backend.
        """
        if "model" in self.model_fields_set:
            return self.model
        return self.model if self.backend == DEFAULT_DRAFT_BACKEND else None

    def selection(self) -> ModelSelection:
        return ModelSelection(backend=self.backend, model=self.effective_model())


class NpcDossiersConfig(BaseModel):
    """The ``<config>/npc_dossiers.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    npc_root: str = DEFAULT_NPC_ROOT
    recent_chapters: int = Field(default=DEFAULT_RECENT_CHAPTERS, ge=0)
    recurring_min: int = Field(default=DEFAULT_RECURRING_MIN, ge=0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    selection: ModelSelection = Field(default_factory=ModelSelection)
    draft: NpcDraftBlock = Field(default_factory=NpcDraftBlock)

    @field_validator("npc_root")
    @classmethod
    def _root_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("npc_root must not be blank")
        return v.strip()


def load_npc_dossiers_config(path: Path) -> NpcDossiersConfig:
    """Load ``npc_dossiers.yaml``; a missing or empty file is the all-defaults config.

    Raises ``ValueError`` on malformed YAML, an unknown key or an invalid value.
    """
    path = Path(path)
    if not path.is_file():
        return NpcDossiersConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path.name}: invalid YAML") from exc
    if not raw:
        return NpcDossiersConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: must be a mapping")
    try:
        return NpcDossiersConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ValueError(f"{path.name}: {problems}") from None


def save_npc_dossiers_config(path: Path, cfg: NpcDossiersConfig) -> None:
    """Write atomically. ``selection`` is written only when set."""
    data: dict[str, Any] = cfg.model_dump(mode="json", exclude={"selection"})
    if not cfg.selection.is_empty():
        data["selection"] = cfg.selection.model_dump(exclude_none=True)
    atomic_write_text(
        Path(path),
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
    )
