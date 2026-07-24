"""Shared session-editor configuration data models and I/O logic.

This module holds the grouped, **strict** (``extra="forbid"``) pydantic
models for the Session Doc Editor's configuration — the target shape from
``docs/config/session-editor-isolation.md`` — plus the YAML load/save pair
that will eventually own ``<config>/session_doc.yaml`` (Phase 5).

In Phase 1 these models are not yet the storage format: the service still
reads/writes through the platform's ``ui.session_doc`` (flat, ``extra=
"allow"``) via an internal adapter. This module is the destination shape
that adapter maps onto, and ``load_/save_session_editor_config`` are
exercised directly (round-trip only) so Phase 5 can flip storage without
touching the model definitions.

Mirrors the structural pattern of ``server/planning_config_shared.py`` /
``server/party_config_shared.py`` (module-level load/save functions used by
both the service layer and, eventually, CLI tooling) but uses pydantic
instead of dataclasses so ``config_models.BackendProfile`` and
``config_models.ProfileEntry`` can be reused directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from server.config_models import BackendProfile, OptStr, ProfileEntry


class EditorPaths(BaseModel):
    """Path selector fields. Session-based vs campaign-based split is
    service-owned metadata (see ``SessionEditorConfigService``), not stored
    per-field here — mirrors ``CampaignConfigService._PATH_FIELDS
    ["session_doc"]``."""

    model_config = ConfigDict(extra="forbid")

    session_recap: OptStr = None
    session_summary: OptStr = None
    scene_extractions_dir: OptStr = None
    roleplay_extractions_dir: OptStr = None
    summary_extractions_dir: OptStr = None
    narration_dir: OptStr = None
    output_dir: OptStr = None
    party: OptStr = None
    voice_dir: OptStr = None
    examples_dir: OptStr = None


class NarrateKnobs(BaseModel):
    """Stage-④ narrate knobs."""

    model_config = ConfigDict(extra="forbid")

    tokens: int = 16000
    prose_mode: bool = False
    reflections: bool = False
    genre: OptStr = None
    batch: bool = False
    context: list[str] = Field(default_factory=list)


class ScrubKnobs(BaseModel):
    """Mechanics-scrub pass knobs."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    tokens: int = 16000


class Roster(BaseModel):
    """Player/character-name mapping inputs."""

    model_config = ConfigDict(extra="forbid")

    characters: OptStr = None
    gm_player: OptStr = None


class Backends(BaseModel):
    """Per-backend memory (O1) + the active selector.

    Each backend keeps its own remembered ``model``/``endpoint`` so
    switching the active backend doesn't lose the others' settings (the
    current flat ``dgx_model``/``openrouter_model`` behavior, generalized).
    The YAML key for Claude Code is the hyphenated ``claude-code``; the
    Python attribute is ``claude_code`` (hyphens aren't valid identifiers),
    bridged via a field alias. ``populate_by_name`` lets internal code
    construct/merge using the attribute name while ``model_dump(by_alias=
    True)`` still serializes the hyphenated key for the on-disk shape in
    ``docs/config/session-editor-isolation.md``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    active: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    anthropic: BackendProfile = Field(default_factory=BackendProfile)
    claude_code: BackendProfile = Field(
        default_factory=BackendProfile, alias="claude-code"
    )
    dgx: BackendProfile = Field(default_factory=BackendProfile)
    openrouter: BackendProfile = Field(default_factory=BackendProfile)


class SessionEditorConfig(BaseModel):
    """Root model — the target ``<config>/session_doc.yaml`` shape.

    Strict (``extra="forbid"``): unlike today's ``SessionDocSection``
    (flat, ``extra="allow"``, two names for several fields), this schema is
    meant to be enforced. See ``docs/config/session-editor-isolation.md``
    for the field-by-field rename table.
    """

    model_config = ConfigDict(extra="forbid")

    paths: EditorPaths = Field(default_factory=EditorPaths)
    narrate: NarrateKnobs = Field(default_factory=NarrateKnobs)
    scrub: ScrubKnobs = Field(default_factory=ScrubKnobs)
    roster: Roster = Field(default_factory=Roster)
    backends: Backends = Field(default_factory=Backends)
    session_name: OptStr = None
    profiles: list[ProfileEntry] = Field(default_factory=list)
    active_profile: OptStr = None


def load_session_editor_config(path: Path) -> SessionEditorConfig:
    """Load a ``session_doc.yaml`` file.

    A missing file, or a file that parses to an empty/null YAML document,
    returns the all-defaults ``SessionEditorConfig`` rather than raising —
    unlike planning's ``npcs``/``factions`` collections, an all-defaults
    session-editor config is a legitimate, meaningful state (a freshly
    created campaign with no editor session picked yet), not an error.

    Malformed YAML (a parse error) still raises ``ValueError``, mirroring
    ``load_planning_config``/``load_party_config``.
    """
    if not path.exists():
        return SessionEditorConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return SessionEditorConfig()
    return SessionEditorConfig.model_validate(raw)


def save_session_editor_config(path: Path, cfg: SessionEditorConfig) -> None:
    """Write ``cfg`` to ``path`` in the grouped YAML shape (``claude-code``
    serialized via its alias), creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = cfg.model_dump(mode="json", by_alias=True)
    path.write_text(
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
