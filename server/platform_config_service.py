"""Service owning the permanent platform tier.

``docs/config/platform-isolation.md`` splits the old ``CampaignConfigService``
(610 lines) into two roles that were previously fused: the permanent
**platform** — path resolution, ``campaign_dir``/``config_dir``, boot
overrides, the read-only ``config.yaml``/wiring view, and (with one
temporary wrinkle below) ``runtime.{default_model, session_dir}`` — and the
transitional **residual landlord** of ten un-isolated ``ui.<section>`` blobs,
which keeps the (renamed, no-alias) ``UIStateService``.

``PlatformConfigService`` is the foundational object: it resolves and
validates ``campaign_dir``, creates ``config_path_base``, loads the
human-owned ``config.yaml`` (``tracked``) and the machine-local
``.campaigngenerator.local.yaml`` (``local``) — and, as the LAST step of its
own construction, builds ``self.uis = UIStateService(self)``. Every other
per-page config service (``SessionEditorConfigService``,
``PlanningConfigService``) composes THIS class the same way
``UIStateService`` does — one platform, several tenants.

## Why ``runtime`` is delegated, not owned outright, this phase

``runtime.{default_model, session_dir}`` is conceptually platform data (the
sidebar model picker, the session-resolution anchor), but it is still
physically persisted INSIDE ``<config>/ui_state.yaml`` — the single document
``UIStateService`` reads and writes whole (atomic temp+replace, one write
lock covering every ``ui.<section>`` write). Splitting ``runtime`` into its
own file is Phase 3 (O3 in the design doc); until then, this class cannot
read or write it without going through the object that owns that document.
So: ``update_runtime``/``runtime`` delegate to ``self.uis.update_runtime``/
``self.uis.ui_state.runtime``. Phase 3 inverts this — ``runtime`` moves into
its own ``<config>/platform.yaml`` that THIS class owns outright, and
``UIStateService`` stops knowing ``runtime`` ever lived next to it.

## Construction-order invariant for ``resolve_path``/``relativize_path``

``self.uis`` does not exist until ``UIStateService(self)`` returns, so
``resolve_path``/``relativize_path``'s ``base="session"`` fallback (which
reads ``self.uis.ui_state.runtime.session_dir`` when the caller doesn't pass
``session_dir`` explicitly) would raise ``AttributeError`` if it fired
*during* that construction call. It never does: every call
``UIStateService.__init__`` makes back into ``self.resolve_path``/
``self.relativize_path`` (via ``_normalize_stored_paths``) passes
``session_dir`` explicitly, so the fallback branch is unreachable until
after ``self.uis`` is assigned. Do not remove that explicit argument from
``UIStateService`` without re-checking this invariant.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from server.config_service import ConfigError, UIStateService
from server.platform_config_shared import (
    LOCAL_CONFIG_NAME,
    PlatformConfig,
    PlatformLocalConfig,
    PlatformRuntime,
    load_local_config,
    save_local_config,
)

# ── Filenames ──────────────────────────────────────────────────────────────

TRACKED_CONFIG_NAME = "config.yaml"


class PlatformConfigService:
    """Owns the platform tier for a single campaign workspace.

    One instance per server process, held as ``app.state.platform`` — the
    canonical handle (there is no ``app.state.config_service`` any more).
    ``self.uis`` reaches the residual ``UIStateService`` for the ten
    ``ui.<section>`` blobs it still owns.
    """

    def __init__(
        self,
        campaign_dir: Path | str,
        *,
        config_dir: str = "config",
        boot_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.campaign_dir: Path = Path(campaign_dir).expanduser().resolve()
        self.config_dir: str = config_dir
        self.boot_overrides: dict[str, Any] = dict(boot_overrides or {})
        self.load_warnings: list[str] = []
        self._write_lock = threading.Lock()

        if not self.campaign_dir.is_dir():
            raise ConfigError(
                f"campaign_dir does not exist: {self.campaign_dir}"
            )

        self.config_path_base: Path = self.campaign_dir / self.config_dir

        try:
            self.config_path_base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise ConfigError(
                f"cannot create or access config directory {self.config_path_base}: {exc}"
            ) from exc

        self._tracked: dict = self._load_tracked()
        self._local, local_warnings = load_local_config(self.local_config_path)
        self.load_warnings.extend(local_warnings)

        # Last step — see class docstring's construction-order invariant.
        self.uis: UIStateService = UIStateService(self)

    # ── Path properties ────────────────────────────────────────────────

    @property
    def config_path(self) -> Path:
        return self.config_path_base / TRACKED_CONFIG_NAME

    @property
    def local_config_path(self) -> Path:
        return self.config_path_base / LOCAL_CONFIG_NAME

    # ── Loaders ────────────────────────────────────────────────────────

    def _load_tracked(self) -> dict:
        path = self.config_path
        if not path.exists():
            raise ConfigError(
                f"no {TRACKED_CONFIG_NAME} in {self.campaign_dir}"
            )
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(
                f"{TRACKED_CONFIG_NAME} is not valid YAML: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ConfigError(
                f"{TRACKED_CONFIG_NAME} top-level must be a mapping"
            )
        return data

    # ── Read views ──────────────────────────────────────────────────────

    @property
    def tracked(self) -> dict:
        """Raw contents of ``config.yaml`` (read-only — never written)."""
        return self._tracked

    @property
    def local(self) -> PlatformLocalConfig:
        return self._local

    @property
    def runtime(self) -> PlatformRuntime:
        """Current PERSISTED runtime values — see module docstring for why
        this reads through ``self.uis`` rather than owning storage
        outright this phase."""
        return PlatformRuntime.model_validate(
            self.uis.ui_state.runtime.model_dump(mode="json")
        )

    @property
    def wiring(self) -> dict:
        """External, mneme-rendered wiring (``config/wiring.yaml``) — see
        ``campaignlib.wiring``. Returns ``{}`` when no rendered file is
        found (e.g. this machine, per the design doc's "Risks" section);
        callers must treat that as "nothing configured", not an error."""
        from campaignlib.wiring import load_wiring

        return load_wiring()

    def snapshot(self) -> PlatformConfig:
        """A single strict, validated view combining ``runtime`` and
        ``local``'s ``server``/``nav`` — the target shape of Phase 3's
        ``<config>/platform.yaml`` for the ``runtime`` portion, assembled
        fresh from today's two stores. See ``PlatformConfig``'s docstring."""
        return PlatformConfig(
            runtime=self.runtime, server=self._local.server, nav=self._local.nav
        )

    # ── Writers ───────────────────────────────────────────────────────

    def update_local(self, partial: dict[str, Any]) -> PlatformLocalConfig:
        """Merge ``partial`` into the local config (top-level keys are
        ``server`` and ``nav``) and persist atomically."""
        with self._write_lock:
            current = self._local.model_dump(mode="json")
            for k, v in partial.items():
                if isinstance(v, dict) and isinstance(current.get(k), dict):
                    current[k].update(v)
                else:
                    current[k] = v
            new_local = PlatformLocalConfig.model_validate(current)
            save_local_config(self.local_config_path, new_local)
            self._local = new_local
        return new_local

    def update_runtime(self, partial: dict[str, Any]) -> PlatformRuntime:
        """Merge ``partial`` into ``runtime`` and persist atomically.

        Delegates the actual write to ``self.uis.update_runtime`` — see
        module docstring for why. Used by the sidebar model picker
        (``default_model``) and SessionConfig (``session_dir``).
        """
        new_state = self.uis.update_runtime(partial)
        return PlatformRuntime.model_validate(new_state.runtime.model_dump(mode="json"))

    # ── Path resolution (single implementation) ─────────────────────────

    def resolve_path(
        self,
        value: str | None,
        *,
        base: str = "campaign",
        session_dir: str | None = None,
    ) -> str | None:
        """Resolve a path string to absolute.

        ``base`` selects the directory a relative path is resolved against:
        ``"campaign"`` (the campaign root) or ``"session"`` (the
        ``runtime.session_dir`` value, falling back to campaign_dir when
        session_dir is unset). Absolute paths and ``~``-expansions pass
        through. ``None`` / empty strings stay as ``None`` so the API
        surface is uniform.

        ``session_dir`` lets the caller pass an explicit session-dir
        override (used by :meth:`UIStateService.resolved` to ensure boot
        CLI overrides of ``runtime.session_dir`` win without persisting).
        When omitted, the value from the persisted ui_state is used — see
        this class's docstring for the construction-order invariant that
        makes that fallback safe.
        """
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        p = Path(s).expanduser()
        if p.is_absolute():
            return str(p.resolve())
        if base == "session":
            sd = session_dir or self.uis.ui_state.runtime.session_dir
            if sd:
                base_path = Path(sd).expanduser()
                if not base_path.is_absolute():
                    base_path = (self.campaign_dir / base_path).resolve()
                return str((base_path / p).resolve())
            # session_dir unset → fall back to campaign root rather than
            # leave the path relative; downstream consumers expect absolute.
        return str((self.campaign_dir / p).resolve())

    def relativize_path(
        self,
        value: str | None,
        *,
        base: str = "campaign",
        session_dir: str | None = None,
    ) -> str | None:
        """Inverse of :meth:`resolve_path` — collapse an absolute path back
        to relative-to-base storage, so persisted values re-track base
        changes the same way hand-authored relative values already do.

        ``None`` / empty strings pass through as ``None``. Values that are
        already relative pass through unchanged (nothing to do). Absolute
        values are relativized against the base directory when they live
        under it; a genuine out-of-tree absolute override (not under the
        base) is returned unchanged, since there is no relative form that
        preserves its meaning.

        For ``base == "session"`` with no resolvable session_dir (neither
        the explicit ``session_dir`` argument nor a persisted
        ``runtime.session_dir``), the value is returned unchanged rather
        than relativized against ``campaign_dir``. Relativizing against
        campaign_dir here would be lossy: a session-scoped field's relative
        storage is always interpreted against ``runtime.session_dir`` at
        read time (see :meth:`resolve_path`), so a value written relative to
        campaign_dir would be silently re-interpreted once a session_dir is
        later set — the same base-mismatch bug this method exists to fix,
        just triggered from the write side. This mirrors the defensive
        "skip session-scoped fields when session_dir is unset" rule used by
        ``UIStateService``'s load-time normalize pass.
        """
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        p = Path(s).expanduser()
        if not p.is_absolute():
            # Already relative — leave as-is, nothing to collapse.
            return value

        if base == "session":
            sd = session_dir or self.uis.ui_state.runtime.session_dir
            if not sd:
                return value
            base_path = Path(sd).expanduser()
            if not base_path.is_absolute():
                base_path = (self.campaign_dir / base_path).resolve()
        else:
            base_path = self.campaign_dir

        resolved_value = p.resolve()
        base_resolved = base_path.resolve()
        if resolved_value.is_relative_to(base_resolved):
            return resolved_value.relative_to(base_resolved).as_posix()
        # Genuine out-of-tree override — no relative form preserves it.
        return value

    # ── Combined resolved view (delegated — see UIStateService.resolved) ──

    def resolved(self) -> dict[str, Any]:
        """The combined ``{campaign_dir, ui, runtime, server, nav}`` view.

        Stays implemented on ``UIStateService`` this phase (design doc's
        "hard design question": minimal churn, Phase 3 revisits) — this is
        a thin passthrough so ``app.state.platform.resolved()`` is the one
        canonical call site regardless of which object does the work.
        """
        return self.uis.resolved()
