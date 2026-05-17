"""Single-authority configuration service.

Replaces the L2/L3/L4 split (``ui_config.yaml`` + boot CLI dict +
``scene_editor.CONFIG``) described in ``docs/configuration.md``.

Three on-disk documents:

    <campaign>/config.yaml                       — tracked, human-only
    <campaign>/ui_state.yaml                     — tracked, server-owned
    <campaign>/.campaigngenerator.local.yaml     — gitignored, machine-local

Two in-memory layers on top:

    boot_overrides   — CLI flags to ``python -m server.main``; in-memory only
    resolved         — typed view with all paths absolute against campaign_dir

The service never opens ``config.yaml`` for write; that file is curated by
the user. Comments and ordering are protected by virtue of no writer
existing.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from server.config_migration import migrate_local_config, migrate_ui_config
from server.config_models import (
    LocalConfig,
    UI_SECTION_NAMES,
    UIState,
)

# ── Filenames ──────────────────────────────────────────────────────────────

TRACKED_CONFIG_NAME = "config.yaml"
UI_STATE_NAME = "ui_state.yaml"
LOCAL_CONFIG_NAME = ".campaigngenerator.local.yaml"
LEGACY_UI_CONFIG_NAME = "ui_config.yaml"
MIGRATION_MARKER_NAME = "ui_config.yaml.migrated"

# ── Path-field knowledge ──────────────────────────────────────────────────
# Per-section, per-field base for path resolution. ``"session"`` resolves
# against ``runtime.session_dir`` (falling back to campaign_dir when that's
# unset); ``"campaign"`` resolves against the campaign root. Anything not
# listed here is passed through unchanged.
#
# The split matches the old ``derive_campaign_paths`` semantics: per-session
# files (gm-assist, session-summary, scene_extractions/, …) live under the
# session dir; campaign-wide assets (party.md, voice/, examples/, the
# canonical timeline summaries.md) live under the campaign root.

_PATH_FIELDS: dict[str, dict[str, str]] = {
    "session_doc": {
        "session": "session",
        "extract_dir": "session",
        "roleplay_dir": "session",
        "output_dir": "session",
        "summary_dir": "session",
        "session_summary": "session",
        "scene_extractions_dir": "session",
        "narration_dir": "session",
        "party": "campaign",
        "voice_dir": "campaign",
        "examples_dir": "campaign",
    },
    "vtt_summary": {
        "input": "session",
        "output": "session",
        "extract_dir": "session",
        "session_summary": "session",
    },
    "grounding": {"summaries": "campaign"},
}

_RUNTIME_PATH_FIELDS: dict[str, str] = {"session_dir": "campaign"}


# ── Errors ─────────────────────────────────────────────────────────────────


class ConfigError(RuntimeError):
    """Raised at startup when a required config file is missing or malformed."""


# ── Service ────────────────────────────────────────────────────────────────


class CampaignConfigService:
    """Owns all configuration for a single campaign workspace.

    One instance per server process. Routers reach it through
    ``request.app.state.config_service``. Concurrent ``update_section`` calls
    on different sections are independent; concurrent calls on the same
    section are serialized by ``self._write_lock`` so writes are last-writer-
    wins per section but never produce a torn file.
    """

    def __init__(
        self,
        campaign_dir: Path | str,
        *,
        boot_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.campaign_dir: Path = Path(campaign_dir).expanduser().resolve()
        self.boot_overrides: dict[str, Any] = dict(boot_overrides or {})
        self.migration_warnings: list[str] = []
        self._write_lock = threading.Lock()

        if not self.campaign_dir.is_dir():
            raise ConfigError(
                f"campaign_dir does not exist: {self.campaign_dir}"
            )

        self._tracked: dict = self._load_tracked()
        self._ui_state: UIState = self._load_or_migrate_ui_state()
        self._local: LocalConfig = self._load_local()

    # ── Path properties ────────────────────────────────────────────────

    @property
    def config_path(self) -> Path:
        return self.campaign_dir / TRACKED_CONFIG_NAME

    @property
    def ui_state_path(self) -> Path:
        return self.campaign_dir / UI_STATE_NAME

    @property
    def local_config_path(self) -> Path:
        return self.campaign_dir / LOCAL_CONFIG_NAME

    @property
    def legacy_ui_config_path(self) -> Path:
        return self.campaign_dir / LEGACY_UI_CONFIG_NAME

    @property
    def migration_marker_path(self) -> Path:
        return self.campaign_dir / MIGRATION_MARKER_NAME

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

    def _load_or_migrate_ui_state(self) -> UIState:
        path = self.ui_state_path
        if path.exists():
            try:
                with path.open(encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(
                    f"{UI_STATE_NAME} is not valid YAML: {exc}"
                ) from exc
            try:
                return UIState.model_validate(raw)
            except ValidationError as exc:
                raise ConfigError(
                    f"{UI_STATE_NAME} failed schema validation: {exc}"
                ) from exc

        # No ui_state.yaml — try to migrate from legacy ui_config.yaml.
        legacy = self.legacy_ui_config_path
        if legacy.exists():
            try:
                with legacy.open(encoding="utf-8") as f:
                    legacy_raw = yaml.safe_load(f) or {}
            except yaml.YAMLError as exc:
                # A broken legacy file shouldn't block startup. Quarantine
                # the whole thing as a single warning and start fresh.
                self.migration_warnings.append(
                    f"{LEGACY_UI_CONFIG_NAME} could not be parsed ({exc}); "
                    f"starting with empty ui_state.yaml"
                )
                state = UIState()
            else:
                state, warnings = migrate_ui_config(legacy_raw)
                self.migration_warnings.extend(warnings)
            self._persist_ui_state(state)
            self._mark_migration_done()
            return state

        # Fresh campaign — no legacy file either.
        return UIState()

    def _load_local(self) -> LocalConfig:
        path = self.local_config_path
        if not path.exists():
            return LocalConfig()
        try:
            with path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            # Local file is machine cruft — refusing to start over a bad
            # nav.last_page would be hostile. Log and treat as empty.
            self.migration_warnings.append(
                f"{LOCAL_CONFIG_NAME} could not be parsed ({exc}); "
                f"ignoring file contents"
            )
            return LocalConfig()
        local, warnings = migrate_local_config(raw)
        self.migration_warnings.extend(warnings)
        return local

    # ── Writers (atomic) ────────────────────────────────────────────────

    def _atomic_write(self, path: Path, text: str) -> None:
        """Write via temp + ``os.replace`` so readers never see a torn file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _persist_ui_state(self, state: UIState) -> None:
        text = yaml.safe_dump(
            state.model_dump(mode="json"),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        self._atomic_write(self.ui_state_path, text)

    def _persist_local(self, local: LocalConfig) -> None:
        text = yaml.safe_dump(
            local.model_dump(mode="json"),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        self._atomic_write(self.local_config_path, text)

    def _mark_migration_done(self) -> None:
        try:
            self.migration_marker_path.touch(exist_ok=True)
        except OSError:
            pass

    # ── Section update API ──────────────────────────────────────────────

    def update_section(self, name: str, partial: dict[str, Any]) -> UIState:
        """Merge ``partial`` into ``ui.<name>`` and persist atomically."""
        if name not in UI_SECTION_NAMES:
            raise ValueError(
                f"unknown UI section {name!r}; "
                f"valid: {', '.join(UI_SECTION_NAMES)}"
            )
        with self._write_lock:
            ui_dict = self._ui_state.ui.model_dump(mode="json")
            section = ui_dict.get(name) or {}
            section.update(partial)
            ui_dict[name] = section
            new_state = self._ui_state.model_copy(
                update={"ui": self._ui_state.ui.__class__.model_validate(ui_dict)}
            )
            self._persist_ui_state(new_state)
            self._ui_state = new_state
        return new_state

    def update_local(self, partial: dict[str, Any]) -> LocalConfig:
        """Merge ``partial`` into the local config (top-level keys are
        ``server`` and ``nav``) and persist atomically."""
        with self._write_lock:
            current = self._local.model_dump(mode="json")
            for k, v in partial.items():
                if isinstance(v, dict) and isinstance(current.get(k), dict):
                    current[k].update(v)
                else:
                    current[k] = v
            new_local = LocalConfig.model_validate(current)
            self._persist_local(new_local)
            self._local = new_local
        return new_local

    # ── Read views ──────────────────────────────────────────────────────

    @property
    def tracked(self) -> dict:
        """Raw contents of ``config.yaml`` (read-only — never written)."""
        return self._tracked

    @property
    def ui_state(self) -> UIState:
        return self._ui_state

    @property
    def local(self) -> LocalConfig:
        return self._local

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
        override (used by :meth:`resolved` to ensure boot CLI overrides
        of ``runtime.session_dir`` win without persisting). When omitted,
        the value from the persisted ui_state is used.
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
            sd = session_dir or self._ui_state.runtime.session_dir
            if sd:
                base_path = Path(sd).expanduser()
                if not base_path.is_absolute():
                    base_path = (self.campaign_dir / base_path).resolve()
                return str((base_path / p).resolve())
            # session_dir unset → fall back to campaign root rather than
            # leave the path relative; downstream consumers expect absolute.
        return str((self.campaign_dir / p).resolve())

    def resolved(self) -> dict[str, Any]:
        """Typed read view with paths resolved (per-field base) and boot
        overrides applied. Returned as plain dicts for JSON friendliness.
        """
        ui_raw = self._ui_state.ui.model_dump(mode="json")
        runtime_raw = self._ui_state.runtime.model_dump(mode="json")
        local_raw = self._local.model_dump(mode="json")

        # Boot overrides must be applied to the path-resolution context BEFORE
        # we resolve session-relative paths — otherwise an override of
        # runtime.session_dir wouldn't change where session-scoped paths land.
        # We apply overrides into the raw dicts first, then resolve.
        for key, value in self.boot_overrides.items():
            section, dot, field = key.partition(".")
            if not dot:
                runtime_raw[key] = value
                continue
            if section == "runtime":
                runtime_raw[field] = value
            elif section == "server":
                local_raw.setdefault("server", {})[field] = value
            else:
                ui_raw.setdefault(section, {})[field] = value

        active_session_dir = runtime_raw.get("session_dir")

        for section, fields in _PATH_FIELDS.items():
            if section not in ui_raw or not isinstance(ui_raw[section], dict):
                continue
            for fname, base in fields.items():
                if fname in ui_raw[section]:
                    ui_raw[section][fname] = self.resolve_path(
                        ui_raw[section][fname],
                        base=base,
                        session_dir=active_session_dir,
                    )

        for fname, base in _RUNTIME_PATH_FIELDS.items():
            if fname in runtime_raw:
                runtime_raw[fname] = self.resolve_path(
                    runtime_raw[fname], base=base,
                )

        return {
            "campaign_dir": str(self.campaign_dir),
            "ui": ui_raw,
            "runtime": runtime_raw,
            "server": local_raw.get("server", {}),
            "nav": local_raw.get("nav", {}),
        }
