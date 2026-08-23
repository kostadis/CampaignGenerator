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
from campaignlib.selection import ModelSelection
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


class BackendProfile(ModelSelection):
    """A selectable execution target for one LLM-bearing stage.

    The API key is NEVER stored here — it is read from the environment
    (ANTHROPIC_API_KEY / OPENROUTER_API_KEY) at run time. ``endpoint`` is used
    for the dgx backend; openrouter uses its own base URL; claude-code bills
    the Pro/Max subscription via the local ``claude`` CLI instead of a key.

    Note ``ensemble.yaml`` has its own ``EnsembleBackend`` with a *plural*
    ``endpoints`` list — the extract stage fans out across DGX hosts. This one
    stays singular; the Session Doc Editor targets one host at a time.
    """

    # extra="allow" is preserved deliberately: unlike its ensemble twin this
    # profile has always tolerated stray keys, and tightening it here would be
    # an unrelated behaviour change riding along with feature 003.
    model_config = ConfigDict(extra="allow")

    # Inherits `backend` and `model` from ModelSelection (feature 003); the
    # only field genuinely its own is the SINGULAR `endpoint` — the Session
    # Doc Editor targets one host at a time, where the ensemble fans out.
    backend: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    endpoint: OptStr = None
    # `batch` (005-ui-batch-selection) is inherited from ModelSelection —
    # this profile IS the editor's per-service selection store, so its
    # `backends.<name>.batch` is what `PUT /api/editor/config` persists and
    # `_editor_service_selection`/`resolve_selection` read back.

    def is_empty(self) -> bool:
        """See EnsembleBackend.is_empty — `backend` is non-optional here, so
        the base class's null test never fires. `batch` participates for the
        same reason it does on the base class's override: a profile that sets
        only `batch` (backend still the default "anthropic", no model/endpoint)
        is not empty — see `ModelSelection.is_empty`."""
        return (
            self.backend == "anthropic"
            and not self.model
            and not self.endpoint
            and self.batch is None
        )


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
    # The genre rulebook is a FILE, not a pasted string (#276 fix 2). It lives
    # here rather than under ``narrate`` so it inherits the path contract every
    # other selector has — relativized on write, resolved absolute on read —
    # instead of needing a second, parallel derivation. Profiles still switch it
    # through the ``narration_genre_file`` knob.
    genre_file: OptStr = None

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


# Retired alongside the bespoke Session Doc Editor batch checkbox
# (005-ui-batch-selection T029, FR-011): `narrate.batch` was that checkbox's
# own persisted store, entirely disconnected from the actual sd_narrate
# command (which never read it) and superseded by `backends.<name>.batch`
# (BackendProfile, via ModelSelection) — the same per-service-selection
# field every other batch consumer now reads through `_selection_args`.
# Stripped on load, not rejected, mirroring RETIRED_PATH_FIELDS above: a
# campaign whose session_doc.yaml still carries the old key from before
# this change would otherwise fail schema validation and take the whole
# editor down on boot.
RETIRED_NARRATE_FIELDS: tuple[str, ...] = ("batch",)

# Retired by #276 fix 2, and called out separately from RETIRED_NARRATE_FIELDS
# because the value is not merely obsolete — it is a *paste* of
# ``voice/_genre.md`` whose canonical home moved to ``paths.genre_file``.
# Dropping it silently would discard a document (out-of-the-abyss carried
# 16,303 characters here), so the notice names the migration that relocates it.
RELOCATED_NARRATE_FIELDS: tuple[str, ...] = ("genre",)


class ExtractKnobs(BaseModel):
    """Stage-② extract knobs.

    No ``enabled`` flag: Extract always runs when the GM triggers Stage 2
    (Extract/Re-Extract) — there is no separate opt-in toggle for it to gate.
    ``tokens`` defaults to 8192, matching ``scene_extract.py``'s own
    ``--max-tokens`` default exactly, so a campaign that has never touched
    this field sees no behavior change.

    ``batch_tokens`` defaults to 32000, sized against the measured ~23K
    tokens of model-generated output for a full 8-scene session. Only the
    ``## Verbatim moments`` body is generated by the model — the
    front-matter, heading and gm-assist summary are assembled locally — so
    the 32000 ceiling leaves roughly 28% headroom.

    ``batch_scenes`` is deliberately TRI-STATE. ``None`` means "not pinned —
    follow the backend default" (the editor pre-selects batching when the
    active backend is ``claude-code``, which has no prompt caching).
    ``True``/``False`` mean the GM pinned it explicitly. Collapsing this to a
    plain ``bool`` would make the pre-selection unrepresentable and force the
    UI to guess.

    ``batch_tokens`` and ``tokens`` are independent: changing one never
    changes the other. They are two different modes with genuinely different
    right answers.
    """

    model_config = ConfigDict(extra="forbid")

    tokens: int = 8192
    batch_scenes: bool | None = None
    batch_tokens: int = 32000


class NarrateKnobs(BaseModel):
    """Stage-④ narrate knobs.

    ``genre`` is deliberately absent: the genre rulebook is a file, addressed
    by ``paths.genre_file``. It used to be pasted here as a string, which meant
    two copies of the same document with no sync and no divergence check — the
    paste in out-of-the-abyss had already drifted to 0.999 similarity against
    its file, and had lost every newline on the way into YAML (#276, #249).
    """

    model_config = ConfigDict(extra="forbid")

    tokens: int = 16000
    prose_mode: bool = False
    reflections: bool = False
    context: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_fields(cls, data: Any) -> Any:
        """Strip retired/relocated keys before ``extra="forbid"`` sees them.

        Announced on stderr rather than dropped silently — see
        ``EditorPaths._drop_retired_fields`` above for the identical
        rationale. A stale key must not take the whole editor down on boot,
        but it must not vanish quietly either.
        """
        if not isinstance(data, dict):
            return data
        retired = [k for k in RETIRED_NARRATE_FIELDS if k in data]
        # Key presence is enough to RETIRE a field, but not to announce a
        # relocation: `genre: null` and `genre: ''` hold no document, so there
        # is nothing being discarded and nothing for the migration to move.
        # obelisk carries `genre: null` and was told, on every config load,
        # that 4 characters were being ignored — `len(str(None))` — and to run
        # a migration with no input. A permanent false alarm on the one stream
        # whose job is to make the real alarm noticeable (#303); the real one,
        # #295, went unnoticed for months.
        def _is_empty(value: Any) -> bool:
            """Holds nothing worth announcing.

            Strings are stripped first: `genre: "   "` and a block scalar
            yielding `"\n"` are empty documents, not "not text". Without the
            strip they failed the `relocated` test AND the emptiness test and
            landed in `odd`, printing "genre (str) ... this value is not text"
            — self-contradictory, and the same per-load false alarm on a new
            value that this whole change exists to remove.
            """
            if isinstance(value, str):
                return not value.strip()
            return value in (None, "", [], {})

        present = [k for k in RELOCATED_NARRATE_FIELDS if k in data]
        # "Holds a document" must mean what the migration means by it —
        # `_paste_from_raw` accepts `isinstance(value, str)` and nothing else.
        # A hand-edited `genre:` written as a YAML list would otherwise be
        # announced with a *repr* length and a migration command that then
        # reports "nothing to migrate".
        relocated = [k for k in present
                     if isinstance(data[k], str) and data[k].strip()]
        # Present, non-empty, and not a string: still dropped (the field is
        # gone), but neither silently nor with advice that cannot work.
        odd = [k for k in present
               if k not in relocated and not _is_empty(data[k])]
        if not retired and not present:
            return data
        if retired:
            print(
                f"  config: dropping retired session_doc.yaml narrate field(s) "
                f"{', '.join(retired)} — batch now lives on the per-backend "
                f"selection (backends.<name>.batch), not narrate.",
                file=sys.stderr,
            )
        if relocated:
            sizes = ", ".join(
                f"{k} ({len(data[k].strip())} chars)" for k in relocated
            )
            print(
                f"  config: ignoring relocated session_doc.yaml narrate field(s) "
                f"{sizes} — the genre rulebook is now a file, addressed by "
                f"paths.genre_file (#276).\n"
                f"    -> this value is NOT reaching Pass 5. Relocate it with:\n"
                f"       python -m server.migrate_narrate_genre --campaign-dir <DIR>",
                file=sys.stderr,
            )
        if odd:
            kinds = ", ".join(f"{k} ({type(data[k]).__name__})" for k in odd)
            print(
                f"  config: discarding session_doc.yaml narrate field(s) {kinds} "
                f"— the genre rulebook is a file at paths.genre_file (#276), and "
                f"this value is not text, so there is nothing to relocate.\n"
                f"    -> write the rulebook to voice/_genre.md and point "
                f"paths.genre_file at it.",
                file=sys.stderr,
            )
        # Every present key is dropped either way: the field no longer exists on
        # the model, and `extra="forbid"` would reject the whole config — taking
        # the editor down on boot — over a value nobody reads.
        drop = set(retired) | set(present)
        return {k: v for k, v in data.items() if k not in drop}


class VerifyKnobs(BaseModel):
    """Quote-verification knobs (`sd_verify_quotes`).

    Deliberately has **no `enabled` flag**. A check you can switch off in
    config is a check that is off exactly when it matters, and its absence
    then reads as a clean result. The GM chooses per run by not invoking it.

    ``threshold`` is the `near`/`unverified` boundary. The 0.85 default was
    derived from *Claude*-generated output (spec 007 research D1: 522 quotes,
    65% exact verbatim, the rest dominated by disfluency edits). It is **not
    calibrated for a local model**, which is the case the feature exists for —
    the repo has been burned by a transplanted threshold before, when
    ``--embed-threshold 0.93`` was measured on one embedding model and stayed
    put after the sidecar was swapped (issue #197, `calibrate_embed.py`).
    Re-measure against real DeepSeek output before trusting it.
    """

    model_config = ConfigDict(extra="forbid")

    threshold: float = 0.85
    min_tokens: int = 4
    report_only: bool = False


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


# Retired with the mechanics-scrub CLI (`session_doc/scrub_mechanics.py`,
# issue #010): that autonomous LLM pass is superseded by the `/scrub` Claude
# Code skill's propose->confirm->apply flow, and `ScrubKnobs` no longer
# exists on the model. Stripped on load, not rejected, mirroring
# RETIRED_PATH_FIELDS/RETIRED_NARRATE_FIELDS above: every campaign that has
# ever opened the Session Doc Editor's config drawer already has a persisted
# top-level `scrub:` block in its session_doc.yaml (the service dumps the
# full model, defaults included), and SessionEditorConfig is
# `extra="forbid"` at the root too — without this, every such campaign would
# fail schema validation and take the whole editor down on boot.
RETIRED_SESSION_DOC_FIELDS: tuple[str, ...] = ("scrub",)


class SessionEditorConfig(BaseModel):
    """Root model — the target ``<config>/session_doc.yaml`` shape.

    Strict (``extra="forbid"``): unlike today's ``SessionDocSection``
    (flat, ``extra="allow"``, two names for several fields), this schema is
    meant to be enforced. See ``docs/config/session-editor-isolation.md``
    for the field-by-field rename table.
    """

    model_config = ConfigDict(extra="forbid")

    paths: EditorPaths = Field(default_factory=EditorPaths)
    extract: ExtractKnobs = Field(default_factory=ExtractKnobs)
    narrate: NarrateKnobs = Field(default_factory=NarrateKnobs)
    verify: VerifyKnobs = Field(default_factory=VerifyKnobs)
    backends: Backends = Field(default_factory=Backends)
    session_name: OptStr = None
    profiles: list[ProfileEntry] = Field(default_factory=list)
    active_profile: OptStr = None

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_fields(cls, data: Any) -> Any:
        """Strip retired top-level keys before ``extra="forbid"`` sees them.

        Announced on stderr rather than dropped silently — see
        ``EditorPaths._drop_retired_fields`` for the identical rationale. A
        stale top-level group must not take the whole editor down on boot,
        but it must not vanish quietly either.
        """
        if not isinstance(data, dict):
            return data
        retired = [k for k in RETIRED_SESSION_DOC_FIELDS if k in data]
        if not retired:
            return data
        print(
            f"  config: dropping retired session_doc.yaml top-level "
            f"field(s) {', '.join(retired)} — the mechanics-scrub CLI they "
            f"configured was retired in favor of the `/scrub` Claude Code "
            f"skill, which has no config-driven knobs.",
            file=sys.stderr,
        )
        return {k: v for k, v in data.items() if k not in RETIRED_SESSION_DOC_FIELDS}


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
    # ``characters`` and ``gm_player`` are deliberately absent (feature 009).
    # They mapped into a ``roster`` group that no longer exists: the narrating
    # cast is derived from ``party.yaml``, and who plays what — including the
    # game master's display names — is recorded in ``players.yaml``. Same
    # rationale as ``narration_genre`` and ``roleplay_dir`` below: reported as
    # unrecognised (visible, left behind in the old ui_state.yaml) rather than
    # migrated into a field that is gone. ``server/migrate_players_config.py``
    # is what harvests them.
    "narrate_tokens": ("narrate", "tokens"),
    "prose_mode": ("narrate", "prose_mode"),
    "reflections": ("narrate", "reflections"),
    # ``narration_genre`` is deliberately absent (#276 fix 2): it mapped into
    # ``narrate.genre``, which no longer exists — the genre rulebook is a file
    # at ``paths.genre_file``. Same rationale as ``roleplay_dir``/``batch``:
    # reported as unrecognised (visible, left behind in the old ui_state.yaml)
    # rather than migrated into a field that is gone. A pre-Phase-5 campaign
    # carrying genre *text* in ui_state.yaml keeps it there, reported and
    # untouched: this migration cannot relocate it, because the destination is
    # now a file on disk and choosing that file's contents is a GM decision.
    # Write ``voice/_genre.md`` by hand and point ``paths.genre_file`` at it.
    # (``server/migrate_narrate_genre.py`` handles the newer case, where the
    # paste is already in session_doc.yaml.)
    # ``batch`` is deliberately absent (005-ui-batch-selection T029): it
    # mapped into the now-retired RETIRED_NARRATE_FIELDS. Same rationale as
    # ``roleplay_dir``/``summary_dir`` above — reported as unrecognised
    # (visible, left behind in the old ui_state.yaml) instead of migrated
    # into a field that no longer exists (silently lost).
    "context": ("narrate", "context"),
    "session_name": ("session_name",),
    "backend": ("backends", "active"),
    "dgx_endpoint": ("backends", "dgx", "endpoint"),
    "dgx_model": ("backends", "dgx", "model"),
    "openrouter_model": ("backends", "openrouter", "model"),
    # ``scrub_enabled``/``scrub_tokens`` are deliberately absent (issue #010):
    # they mapped into the ``scrub`` group, which no longer exists on
    # SessionEditorConfig — the mechanics-scrub CLI it configured was retired
    # in favor of the `/scrub` Claude Code skill, which has no config-driven
    # knobs. Same rationale as ``roleplay_dir``/``narration_genre`` above:
    # reported as unrecognised (visible, left behind in the old ui_state.yaml)
    # instead of migrated into a field that is gone.
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
