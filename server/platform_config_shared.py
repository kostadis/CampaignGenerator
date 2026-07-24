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

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.config_models import OptStr

LOCAL_CONFIG_NAME = ".campaigngenerator.local.yaml"
PLATFORM_CONFIG_NAME = "platform.yaml"


class PlatformRuntime(BaseModel):
    """The platform-owned ``runtime`` slice — ``default_model`` (the sidebar
    model picker) and ``session_dir`` (the session-resolution anchor every
    session-scoped path resolves against). Physically persisted as the
    ``runtime:`` key of ``<config>/platform.yaml`` (Phase 3, O3) — see module
    docstring for the pre-Phase-3 shape this replaced."""

    model_config = ConfigDict(extra="forbid")

    default_model: str = Field(
        default_factory=lambda: os.environ.get("CAMPAIGN_MODEL") or "claude-sonnet-4-6"
    )
    session_dir: OptStr = None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        cfg.model_dump(mode="json"),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        cfg.model_dump(mode="json"),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
