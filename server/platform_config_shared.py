"""Shared platform configuration data models and I/O logic.

Two documents make up the platform's own state, and this phase leaves both
physically where they already are (``docs/config/platform-isolation.md``
calls Phase 2 "deliberately storage-neutral" — the data lift to a dedicated
``<config>/platform.yaml`` is Phase 3, gated on O3):

    runtime  — the ``runtime`` key of ``<config>/ui_state.yaml``. That file
               is still owned end-to-end by ``UIStateService`` (the atomic
               whole-document read/write, the ten ``ui.<section>`` blobs it
               is the residual landlord of), so this module does NOT define
               a loader for it — ``PlatformConfigService`` reads/writes the
               ``runtime`` slice by delegating to ``UIStateService``. See
               ``server/platform_config_service.py``'s docstring for why.
    local    — ``<config>/.campaigngenerator.local.yaml`` (gitignored,
               machine-only: ``server.{host,port}`` + ``nav.last_page``).
               Unlike ``runtime``, this file has never overlapped with
               ``ui_state.yaml`` — nothing else reads or writes it — so
               ``PlatformConfigService`` owns its load/save outright, no
               delegation needed. The module-level ``load_local_config`` /
               ``save_local_config`` pair here is that implementation,
               mirroring ``session_editor_config_shared.py``'s
               ``load_/save_session_editor_config``.

``PlatformRuntime`` / ``PlatformServer`` / ``PlatformNav`` are STRICT
(``extra="forbid"``) twins of ``config_models.RuntimeSection`` /
``ServerSection`` / ``NavSection`` — the untyped originals stay put and
``extra="allow"``-ish (Phase 3 tightens ``runtime`` for real once it has its
own file; ``ServerSection``/``NavSection``/``LocalConfig`` are retired from
``config_models.py`` entirely now that ``local`` has a single owner).
``PlatformConfig`` combines all three into one validated read-shape — the
literal target shape of Phase 3's ``<config>/platform.yaml`` for the
``runtime`` portion, synthesized here from two stores for one typed view in
the meantime (mirrors how ``resolved()`` has always assembled one combined
dict from files that don't structurally match it).

Per the design doc's "Strictness rule": tightening ``local`` to
``extra="forbid"`` must not turn a stray hand-edited or stale key into a
boot-blocking crash — these are machine-written files. ``load_local_config``
therefore warns and drops on a validation failure, returning the all-defaults
config, exactly mirroring ``CampaignConfigService._load_local``'s existing
precedent (now moved here alongside the models it validates).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.config_models import OptStr

LOCAL_CONFIG_NAME = ".campaigngenerator.local.yaml"


class PlatformRuntime(BaseModel):
    """Strict twin of ``config_models.RuntimeSection`` — the platform-owned
    subset of ``runtime`` (``default_model``, ``session_dir``). Physically
    persisted inside ``ui_state.yaml`` this phase (see module docstring);
    this is the typed shape ``PlatformConfigService`` reads/writes it as."""

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


class PlatformConfig(BaseModel):
    """Combined, strict view of everything ``PlatformConfigService`` owns —
    ``runtime`` (delegated storage this phase) plus ``local``'s ``server``/
    ``nav`` (owned storage). NOT the literal shape of a single on-disk
    document yet: ``runtime`` and ``local`` remain two independent files
    until Phase 3 relocates ``runtime`` into its own ``<config>/
    platform.yaml`` (see the design doc's sketch of that file — this
    model's ``runtime`` field is exactly that future shape, assembled here
    early for one typed accessor). Constructed fresh by
    ``PlatformConfigService`` on demand; never itself round-tripped to
    disk."""

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
