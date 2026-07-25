"""Shared session-editor configuration data models and I/O logic.

This module holds the grouped, **strict** (``extra="forbid"``) pydantic
models for the Session Doc Editor's configuration — the target shape from
``docs/config/session-editor-isolation.md`` — plus the YAML load/save pair
that owns ``<config>/session_doc.yaml`` (Phase 5: this IS the storage
format; ``SessionEditorConfigService`` reads/writes through
``load_/save_session_editor_config`` directly, no adapter).

Also holds ``TYPED_SESSION_DOC_TO_GROUPED``, the flat-legacy (old
``ui.session_doc``) -> grouped remap table used only by the one-shot
``server/migrate_session_doc.py`` CLI to read pre-Phase-5 ``ui_state.yaml``
data.

Mirrors the structural pattern of ``campaignlib/planning_config.py`` /
``campaignlib/party_config.py`` (module-level load/save functions used by
both the service layer and CLI tooling) but uses pydantic instead of
dataclasses so ``config_models.BackendProfile`` and
``config_models.ProfileEntry`` can be reused directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.platform_config_shared import OptStr


# ── Editor-owned models that used to live in server/config_models.py ──────
# ``ProfileEntry`` and ``BackendProfile`` were declared next to ``UIState``
# back when the editor's config WAS a ``ui_state.yaml`` section. Phase 5 of
# the session-editor isolation moved the data into ``session_doc.yaml`` but
# left these two models behind; ``docs/config/ui-state-retirement.md`` D2
# finishes the job, since this file — ``session_doc.yaml``'s schema — is the
# only place either is used.


class ProfileEntry(BaseModel):
    """A named preset of Stage-④ Narrate knobs.

    Paths are NOT part of a profile — they are per-session. Only the knobs
    that change between runs (token budget, prose mode, reflections, the
    enhanced-sections toggle, the genre directive, the backend choice) are
    captured.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    knobs: dict[str, Any] = Field(default_factory=dict)


class BackendProfile(BaseModel):
    """A selectable execution target for one LLM-bearing stage.

    The API key is NEVER stored here — it is read from the environment
    (ANTHROPIC_API_KEY / OPENROUTER_API_KEY) at run time. ``endpoint`` is used
    for the dgx backend; openrouter uses its own base URL; claude-code bills
    the Pro/Max subscription via the local ``claude`` CLI instead of a key.

    Note ``ensemble.yaml`` has its own ``EnsembleBackend`` with a *plural*
    ``endpoints`` list — the extract stage fans out across DGX hosts. This one
    stays singular; the Session Doc Editor targets one host at a time.
    """

    model_config = ConfigDict(extra="allow")

    backend: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    endpoint: OptStr = None
    model: OptStr = None


# Dropped with the ``vtt_summary`` chain: the extraction directories it
# produced now have neither a producer nor a consumer. They are stripped on
# load rather than rejected — ``EditorPaths`` is ``extra="forbid"``, so a
# campaign whose ``session_doc.yaml`` still carries them (every campaign
# migrated by ``server/migrate_session_doc.py``, which mapped the old
# ``roleplay_dir``/``summary_dir`` into them) would otherwise fail schema
# validation and take the whole Session Doc Editor down on boot.
RETIRED_PATH_FIELDS: tuple[str, ...] = (
    "roleplay_extractions_dir",
    "summary_extractions_dir",
)


class EditorPaths(BaseModel):
    """Path selector fields. Session-based vs campaign-based split is
    service-owned metadata (see ``SessionEditorConfigService``), not stored
    per-field here — mirrors the pre-Phase-5 ``CampaignConfigService.
    _PATH_FIELDS["session_doc"]`` (that class is now split into
    ``PlatformConfigService``/``UIStateService`` per
    ``docs/config/platform-isolation.md``; the still-live analogue is
    ``UIStateService._PATH_FIELDS``)."""

    model_config = ConfigDict(extra="forbid")

    session_recap: OptStr = None
    session_summary: OptStr = None
    scene_extractions_dir: OptStr = None
    narration_dir: OptStr = None
    output_dir: OptStr = None
    party: OptStr = None
    voice_dir: OptStr = None
    examples_dir: OptStr = None

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_fields(cls, data: Any) -> Any:
        """Strip retired keys before ``extra="forbid"`` sees them.

        Announced on stderr rather than dropped silently: the value is
        being discarded from disk on the next write, and a GM who hand-set
        one of these paths should be told it stopped meaning anything.
        """
        if not isinstance(data, dict):
            return data
        retired = [k for k in RETIRED_PATH_FIELDS if k in data]
        if not retired:
            return data
        print(
            f"  config: dropping retired session_doc.yaml path field(s) "
            f"{', '.join(retired)} — the vtt_summary chain that produced "
            f"those directories has been removed.",
            file=sys.stderr,
        )
        return {k: v for k, v in data.items() if k not in RETIRED_PATH_FIELDS}


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


# Typed `ui.session_doc` field name -> grouped-schema location, expressed as
# a tuple path into the nested SessionEditorConfig shape. The single
# authority for the flat-legacy -> grouped remap, consumed by
# ``server/migrate_session_doc.py`` (the one-shot CLI that moves
# ``ui.session_doc``/``ui.profiles`` out of a pre-Phase-5 ``ui_state.yaml``
# into a dedicated ``session_doc.yaml``). This used to live as the service's
# internal ``_TYPED_TO_GROUPED`` adapter table (deleted when the service
# flipped storage) — it survives here because the migration CLI still needs
# it to read OLD-shape data.
TYPED_SESSION_DOC_TO_GROUPED: dict[str, tuple[str, ...]] = {
    "session": ("paths", "session_recap"),
    "session_summary": ("paths", "session_summary"),
    "scene_extractions_dir": ("paths", "scene_extractions_dir"),
    # ``roleplay_dir``/``summary_dir`` are deliberately absent: they mapped
    # into the now-retired RETIRED_PATH_FIELDS. The migration reports them
    # as unrecognised (visible) instead of migrating them into a field that
    # no longer exists (silently lost).
    "narration_dir": ("paths", "narration_dir"),
    "output_dir": ("paths", "output_dir"),
    "party": ("paths", "party"),
    "voice_dir": ("paths", "voice_dir"),
    "examples_dir": ("paths", "examples_dir"),
    "characters": ("roster", "characters"),
    "gm_player": ("roster", "gm_player"),
    "narrate_tokens": ("narrate", "tokens"),
    "prose_mode": ("narrate", "prose_mode"),
    "reflections": ("narrate", "reflections"),
    "narration_genre": ("narrate", "genre"),
    "batch": ("narrate", "batch"),
    "context": ("narrate", "context"),
    "session_name": ("session_name",),
    "backend": ("backends", "active"),
    "dgx_endpoint": ("backends", "dgx", "endpoint"),
    "dgx_model": ("backends", "dgx", "model"),
    "openrouter_model": ("backends", "openrouter", "model"),
    "scrub_enabled": ("scrub", "enabled"),
    "scrub_tokens": ("scrub", "tokens"),
    # -- extras, no typed source field --
    # The old typed `ui.session_doc` model never had a slot for an
    # editor-local anthropic/claude-code model override (O3 was a new
    # decision, not carried forward from the flat shape) — nothing in a
    # pre-Phase-5 ui_state.yaml can populate these, but they're listed for
    # completeness / documentation of the full grouped target shape.
    "anthropic_model": ("backends", "anthropic", "model"),
    "claude_code_model": ("backends", "claude_code", "model"),
    # NOTE: the legacy typed `extract_dir` is a dead duplicate of
    # `scene_extractions_dir` (S4 in the design doc) — deliberately not
    # mapped.
}


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
