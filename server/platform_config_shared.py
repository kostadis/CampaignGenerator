"""Shared platform configuration data models and I/O logic.

Two documents make up the platform's own state, both owned outright by
``PlatformConfigService`` — no delegation to ``UIStateService`` for either,
as of Phase 3 (O3) of ``docs/config/platform-isolation.md``:

    runtime  — ``<config>/platform.yaml`` (tracked, server-owned). Holds
               ``runtime.{default_model, session_dir}`` — the sidebar model
               picker and the session-resolution anchor every session-scoped
               path resolves against. Through Phase 2 this lived physically
               INSIDE ``<config>/ui_state.yaml`` and ``PlatformConfigService``
               could only reach it by delegating to ``UIStateService`` (the
               object that owned that document's atomic read/write). Phase 3
               relocates it to its own file and inverts the delegation: this
               module now defines ``PlatformDocument`` (the literal on-disk
               shape) and ``load_/save_platform_config``, and
               ``UIStateService`` stops knowing ``runtime`` ever lived next
               to it — see ``server/platform_config_service.py``'s and
               ``server/config_service.py``'s module docstrings.
    local    — ``<config>/.campaigngenerator.local.yaml`` (gitignored,
               machine-only: ``server.{host,port}`` + ``nav.last_page``).
               This file has never overlapped with ``ui_state.yaml`` —
               nothing else reads or writes it — so ``PlatformConfigService``
               has owned its load/save outright since Phase 2. The
               module-level ``load_local_config`` / ``save_local_config``
               pair here is that implementation, mirroring
               ``session_editor_config_shared.py``'s
               ``load_/save_session_editor_config``.

``PlatformRuntime`` / ``PlatformServer`` / ``PlatformNav`` are STRICT
(``extra="forbid"``) — the pre-Phase-2 untyped originals (``RuntimeSection``/
``ServerSection``/``NavSection``) are retired from ``config_models.py``
entirely now that both ``runtime`` and ``local`` have a single owner each.
``PlatformDocument`` is the literal root shape of ``<config>/platform.yaml``
— a single ``runtime:`` key — matching the design doc's data-model sketch and
the strictness of ``SessionEditorConfig``/``PlanningConfig``.
``PlatformConfig`` is a DIFFERENT thing: a combined, validated read-shape
spanning both documents (``runtime`` from ``platform.yaml`` plus ``server``/
``nav`` from the local file) for ``PlatformConfigService.snapshot()`` — never
itself round-tripped to disk, since no single on-disk document has that
shape (mirrors how ``resolved()`` has always assembled one combined dict
from files that don't structurally match it).

Per the design doc's "Strictness rule": tightening ``local`` to
``extra="forbid"`` must not turn a stray hand-edited or stale key into a
boot-blocking crash — these are machine-written files. ``load_local_config``
therefore warns and drops on a validation failure, returning the all-defaults
config, exactly mirroring ``CampaignConfigService._load_local``'s existing
precedent (now moved here alongside the models it validates).
``load_platform_config`` does NOT get the same warn-and-drop treatment —
unlike the local file (genuine machine cruft nobody hand-edits, tolerant by
design) ``platform.yaml`` mirrors ``session_doc.yaml``'s contract exactly: a
missing file is a legitimate first-launch state (returns all-defaults, no
error), but malformed YAML or a schema mismatch raises, because the value it
guards (``runtime.session_dir``) is load-bearing for every session-scoped
path resolved at construction time — see
``server/platform_config_service.py``'s construction-order note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from campaignlib import DEFAULT_MODEL
from campaignlib.util import atomic_write_text
from campaignlib.selection import (  # noqa: F401  (re-exported)
    BACKENDS,
    CODEX_REASONING_EFFORTS,
    Backend,
    CodexReasoningEffort,
    ModelSelection,
    compatible,
)

LOCAL_CONFIG_NAME = ".campaigngenerator.local.yaml"
PLATFORM_CONFIG_NAME = "platform.yaml"


# ── Shared validators and the config error type ───────────────────────────
# These lived in ``server/config_models.py`` alongside ``UIState`` until
# ``docs/config/ui-state-retirement.md`` retired that module with the rest of
# the ``ui_state.yaml`` tier. They are not platform-specific in themselves,
# but the platform is the one tier every other config service already composes
# — so this is the module they can live in without anything importing
# "upward". Per D2: each orphaned symbol lands with its owner.
#
# ``ConfigError`` in particular belongs here rather than where it was defined
# (``UIStateService``): ``server/main.py`` catches it to report a fatal
# boot-time config failure, and the documents that can trigger one
# (``config.yaml``, ``platform.yaml``) are both platform-owned.


def _empty_to_none(v: Any) -> Any:
    """Treat empty/whitespace strings as 'unset' so type defaults take over."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _none_to_false(v: Any) -> Any:
    """Coerce a YAML/JSON ``null`` to ``False`` so a write that leaves a bool
    field unset never breaks schema validation."""
    return False if v is None else v


OptStr = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptBool = Annotated[bool, BeforeValidator(_none_to_false)]


class ConfigError(RuntimeError):
    """Raised at startup when a required config file is missing or malformed."""


# ── Model/backend selection (feature 003) ─────────────────────────────────
# Defined in campaignlib.selection and re-exported here. That module is the
# lower layer — it is where the backends are actually spoken to
# (campaignlib/api/client.py declares the same four names as its --backend
# choices) and where DEFAULT_MODEL already lives. The forcing function is
# PartyConfig/PlanningConfig: they are campaignlib models, and a service
# document carrying a `selection` field cannot import one from `server`
# without inverting the layering.

class PlatformRuntime(BaseModel):
    """The platform-owned ``runtime`` slice — ``default_model`` and
    ``default_backend`` (the sidebar's two pickers) and ``session_dir`` (the
    session-resolution anchor every session-scoped path resolves against).
    Physically persisted as the ``runtime:`` key of
    ``<config>/platform.yaml`` (Phase 3, O3) — see module docstring for the
    pre-Phase-3 shape this replaced.

    ``default_backend`` arrived with feature 003. Before it, the sidebar's
    BACKEND toggle wrote ``session_doc.yaml``'s ``backends.active`` — the
    Session Doc Editor's *own* config — while the MODEL picker beside it
    wrote here. Two controls presented as global, owned by different tiers:
    that asymmetry is why ``grounding.py`` had to reach into the editor's
    service to find a backend, and why a Grounding run could carry a model
    from one owner and a backend from another. The default is ``anthropic``
    because ``backend_cli_args`` emits nothing for that value, so a campaign
    that never touches the toggle behaves exactly as it did before.

    ``default_model``'s ``default_factory`` reads ``campaignlib.constants.
    DEFAULT_MODEL`` (Phase 5a,
    ``docs/config/platform-isolation.md``) rather than re-deriving
    ``os.environ.get("CAMPAIGN_MODEL") or "claude-sonnet-4-6"`` independently
    — this was the second of three copies of that expression (the third
    was ``server/config.py``'s own ``DEFAULT_MODEL``, also now consolidated).
    Behaviorally identical: ``campaignlib.constants.DEFAULT_MODEL`` is
    computed from the same env lookup at import time, and ``CAMPAIGN_MODEL``
    does not change mid-process.

    ``default_batch`` arrived with feature 005-ui-batch-selection — the
    app-wide Message Batches toggle, alongside the model/backend pickers in
    the sidebar. Resolved with the same request → service → platform
    precedence as ``default_backend`` (``server.platform_config_service.
    resolve_selection``), but independently: the model/backend *pairing*
    rule does not extend to batch (research D2 of that spec) — a service
    that overrides only ``batch`` must not thereby inherit this tier's model
    or backend. Defaults to ``False`` (FR-004: an operator who never touches
    the toggle sees no change in behavior). Uses ``OptBool`` rather than a
    bare ``bool`` so a partial write that leaves this field an explicit
    ``null`` coerces to ``False`` instead of failing validation — the same
    protection ``OptStr`` already gives the string fields above."""

    model_config = ConfigDict(extra="forbid")

    default_model: str = Field(default_factory=lambda: DEFAULT_MODEL)
    default_backend: Backend = "anthropic"
    # Remember the last model chosen for each backend.  ``default_model`` is
    # retained as the active/global compatibility field for older clients and
    # platform files; this map is the durable owner of the sidebar's
    # backend-specific model memory.
    default_models: dict[Backend, OptStr] = Field(default_factory=dict)
    session_dir: OptStr = None
    default_batch: OptBool = False
    default_codex_reasoning_effort: CodexReasoningEffort | None = None


class PlatformServer(BaseModel):
    """Strict twin of ``config_models.ServerSection`` — host/port the
    server was last launched/saved with."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 5000


class PlatformNav(BaseModel):
    """Strict twin of ``config_models.NavSection`` — last page visited, for
    cold-start restore. ``extra="allow"`` on the old model let the frontend
    stash ad hoc scroll/UI state alongside ``last_page``; tightened here per
    the design doc, with the same warn-and-drop safety net as everything
    else in this module."""

    model_config = ConfigDict(extra="forbid")

    last_page: OptStr = None


class PlatformLocalConfig(BaseModel):
    """Root model for ``<config>/.campaigngenerator.local.yaml`` — the
    literal on-disk shape (``server`` + ``nav`` top-level keys), unchanged
    by this phase. Strict, unlike the retired ``config_models.LocalConfig``
    it replaces; see ``load_local_config`` for how a stray key is handled
    instead of raising."""

    model_config = ConfigDict(extra="forbid")

    server: PlatformServer = Field(default_factory=PlatformServer)
    nav: PlatformNav = Field(default_factory=PlatformNav)


class PlatformDocument(BaseModel):
    """Root model for ``<config>/platform.yaml`` (Phase 3, O3) — the literal
    on-disk shape: a single ``runtime:`` key. Strict (``extra="forbid"``),
    matching ``SessionEditorConfig``/``PlanningConfig`` per the design doc's
    data model. This IS the document ``load_/save_platform_config``
    round-trip — unlike ``PlatformConfig`` below, which spans two files."""

    model_config = ConfigDict(extra="forbid")

    runtime: PlatformRuntime = Field(default_factory=PlatformRuntime)


class PlatformConfig(BaseModel):
    """Combined, strict view of everything ``PlatformConfigService`` owns —
    ``runtime`` (from ``platform.yaml``) plus ``local``'s ``server``/``nav``
    (from ``.campaigngenerator.local.yaml``). NOT the literal shape of a
    single on-disk document — the two stay two independent files, unlike
    ``session_doc.yaml``'s single-file consolidation, because ``local`` has
    never overlapped with either. Constructed fresh by
    ``PlatformConfigService.snapshot()`` on demand; never itself
    round-tripped to disk."""

    model_config = ConfigDict(extra="forbid")

    runtime: PlatformRuntime = Field(default_factory=PlatformRuntime)
    server: PlatformServer = Field(default_factory=PlatformServer)
    nav: PlatformNav = Field(default_factory=PlatformNav)


def load_local_config(path: Path) -> tuple[PlatformLocalConfig, list[str]]:
    """Load ``.campaigngenerator.local.yaml``, warning and dropping on a
    parse or schema failure rather than raising.

    Returns ``(config, warnings)`` — ``warnings`` is empty on a clean load
    (including a missing file, which is a legitimate first-launch state, not
    an error). A caller that wants the previous ``ConfigError``-raising
    behavior for a *different* file should not reuse this helper — this
    warn-and-drop contract is specific to the local file, which is machine
    cruft nobody hand-edits; refusing to boot over a bad ``nav.last_page``
    entry would be hostile. Mirrors the (now-moved)
    ``CampaignConfigService._load_local`` exactly.
    """
    if not path.exists():
        return PlatformLocalConfig(), []
    warnings: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        warnings.append(
            f"{LOCAL_CONFIG_NAME} could not be parsed ({exc}); ignoring file contents"
        )
        return PlatformLocalConfig(), warnings
    try:
        return PlatformLocalConfig.model_validate(raw), warnings
    except ValidationError as exc:
        warnings.append(
            f"{LOCAL_CONFIG_NAME} failed schema validation ({exc}); ignoring file contents"
        )
        return PlatformLocalConfig(), warnings


def save_local_config(path: Path, cfg: PlatformLocalConfig) -> None:
    """Write ``cfg`` to ``path`` atomically (temp file + ``os.replace``, so
    a reader never observes a torn file) — the same crash-safety guarantee
    ``CampaignConfigService`` gave ``ui_state.yaml``, preserved here now that
    ``local`` has moved to its own owner."""
    text = yaml.safe_dump(
        cfg.model_dump(mode="json"),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    atomic_write_text(path, text)


def load_platform_config(path: Path) -> PlatformDocument:
    """Load ``<config>/platform.yaml``.

    A missing file, or a file that parses to an empty/null YAML document,
    returns the all-defaults ``PlatformDocument`` rather than raising — a
    freshly created campaign that has never saved a model choice or session
    directory is a legitimate state, not an error. Mirrors
    ``load_session_editor_config`` exactly, deliberately NOT the
    warn-and-drop contract ``load_local_config`` uses above: ``platform.yaml``
    is exclusively server-written (nobody hand-edits it, unlike the local
    file) and holds ``runtime.session_dir`` — load-bearing for every
    session-scoped path resolved during ``PlatformConfigService``
    construction — so a malformed file should surface loudly rather than
    silently discard state a user may not realize was corrupted.

    Malformed YAML raises ``ValueError``. A schema mismatch (unrecognized
    key, since ``PlatformDocument``/``PlatformRuntime`` are strict) raises
    ``pydantic.ValidationError`` unguarded, same as
    ``load_session_editor_config``. ``PlatformConfigService.__init__``
    catches both and re-raises as ``ConfigError`` so construction-time
    failures surface through the one error type ``server/main.py`` already
    handles.
    """
    if not path.exists():
        return PlatformDocument()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return PlatformDocument()
    return PlatformDocument.model_validate(raw)


def save_platform_config(path: Path, cfg: PlatformDocument) -> None:
    """Write ``cfg`` to ``path`` atomically (temp file + ``os.replace``, so
    a reader never observes a torn file) — the same crash-safety guarantee
    ``save_local_config`` gives the local file, and ``UIStateService``'s
    ``_atomic_write`` gives ``ui_state.yaml``. Caller (``PlatformConfigService.
    update_runtime``) holds its write lock around this call, matching the
    other two writers in this module/service pair."""
    text = yaml.safe_dump(
        cfg.model_dump(mode="json"),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    atomic_write_text(path, text)
