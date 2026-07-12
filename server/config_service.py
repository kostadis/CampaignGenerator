"""Single-authority configuration service.

Replaces the L2/L3/L4 split (``ui_config.yaml`` + boot CLI dict +
``scene_editor.CONFIG``) described in ``docs/configuration.md``.

Three on-disk documents in <campaign>/<config-dir>/:

    <campaign>/<config-dir>/config.yaml                       — tracked, human-only
    <campaign>/<config-dir>/ui_state.yaml                     — tracked, server-owned
    <campaign>/<config-dir>/.campaigngenerator.local.yaml     — gitignored, machine-local

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

from server.config_models import (
    LocalConfig,
    UI_SECTION_NAMES,
    UIState,
)

# ── Filenames ──────────────────────────────────────────────────────────────

TRACKED_CONFIG_NAME = "config.yaml"
UI_STATE_NAME = "ui_state.yaml"
LOCAL_CONFIG_NAME = ".campaigngenerator.local.yaml"

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

        # Build the path to the config subdirectory
        self.config_path_base: Path = self.campaign_dir / self.config_dir

        # Ensure the config subdirectory exists
        try:
            self.config_path_base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise ConfigError(
                f"cannot create or access config directory {self.config_path_base}: {exc}"
            ) from exc

        self._tracked: dict = self._load_tracked()
        self._ui_state: UIState = self._load_ui_state()
        self._normalize_stored_paths()
        self._local: LocalConfig = self._load_local()

    # ── Path properties ────────────────────────────────────────────────

    @property
    def config_path(self) -> Path:
        return self.config_path_base / TRACKED_CONFIG_NAME

    @property
    def ui_state_path(self) -> Path:
        return self.config_path_base / UI_STATE_NAME

    @property
    def local_config_path(self) -> Path:
        return self.config_path_base / LOCAL_CONFIG_NAME

    @property
    def migration_warnings(self) -> list[str]:
        """Back-compat alias — the warning list is no longer migration-specific."""
        return self.load_warnings

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

    def _load_ui_state(self) -> UIState:
        path = self.ui_state_path
        if not path.exists():
            return UIState()
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
            self.load_warnings.append(
                f"{LOCAL_CONFIG_NAME} could not be parsed ({exc}); "
                f"ignoring file contents"
            )
            return LocalConfig()
        try:
            return LocalConfig.model_validate(raw)
        except ValidationError as exc:
            self.load_warnings.append(
                f"{LOCAL_CONFIG_NAME} failed schema validation ({exc}); "
                f"ignoring file contents"
            )
            return LocalConfig()

    def _normalize_stored_paths(self) -> None:
        """One-time load-time self-heal for pre-existing ``ui_state.yaml``
        files written before the write-time relativization choke point in
        :meth:`update_section` existed.

        Rewrites absolute ``session_doc`` / ``vtt_summary`` / ``grounding``
        path fields to relative storage when they already sit under the
        applicable base, using the CURRENTLY PERSISTED ``runtime.session_dir``
        (not any boot override) as the session base. Session-scoped fields
        are left untouched when ``runtime.session_dir`` is unset — same
        guard as :meth:`relativize_path` itself, for the same reason: there
        is no base to relativize against yet. Persists only if at least one
        field actually changed.
        """
        sections_to_check = ("session_doc", "vtt_summary", "grounding")
        persisted_session_dir = self._ui_state.runtime.session_dir

        ui_dict = self._ui_state.ui.model_dump(mode="json")
        changed = False
        for section_name in sections_to_check:
            fields = _PATH_FIELDS.get(section_name, {})
            section = ui_dict.get(section_name)
            if not fields or not isinstance(section, dict):
                continue
            for field, base in fields.items():
                value = section.get(field)
                if not isinstance(value, str) or not value:
                    continue
                new_value = self.relativize_path(
                    value, base=base, session_dir=persisted_session_dir
                )
                if new_value != value:
                    section[field] = new_value
                    changed = True

        if not changed:
            return
        new_state = self._ui_state.model_copy(
            update={"ui": self._ui_state.ui.__class__.model_validate(ui_dict)}
        )
        self._persist_ui_state(new_state)
        self._ui_state = new_state

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

    # ── Section update API ──────────────────────────────────────────────

    def update_section(self, name: str, partial: dict[str, Any]) -> UIState:
        """Merge ``partial`` into ``ui.<name>`` and persist atomically."""
        if name not in UI_SECTION_NAMES:
            raise ValueError(
                f"unknown UI section {name!r}; "
                f"valid: {', '.join(UI_SECTION_NAMES)}"
            )
        with self._write_lock:
            path_fields = _PATH_FIELDS.get(name, {})
            to_store = dict(partial)
            for field, raw_value in partial.items():
                if field in path_fields:
                    to_store[field] = self.relativize_path(
                        raw_value, base=path_fields[field]
                    )
            ui_dict = self._ui_state.ui.model_dump(mode="json")
            section = ui_dict.get(name) or {}
            section.update(to_store)
            ui_dict[name] = section
            new_state = self._ui_state.model_copy(
                update={"ui": self._ui_state.ui.__class__.model_validate(ui_dict)}
            )
            self._persist_ui_state(new_state)
            self._ui_state = new_state
        return new_state

    def update_runtime(self, partial: dict[str, Any]) -> UIState:
        """Merge ``partial`` into ``runtime`` and persist atomically.

        Used by the sidebar model picker (``default_model``) and SessionConfig
        (``session_dir``). Boot overrides for the same keys still win at
        ``resolved()`` time for the lifetime of the process; this writer just
        keeps the on-disk value in sync with the UI for next launch.
        """
        with self._write_lock:
            current = self._ui_state.runtime.model_dump(mode="json")
            current.update(partial)
            new_runtime = self._ui_state.runtime.__class__.model_validate(current)
            new_state = self._ui_state.model_copy(update={"runtime": new_runtime})
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
        the load-time normalize pass.
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
            sd = session_dir or self._ui_state.runtime.session_dir
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

        # If runtime.session_dir was overridden at boot, rebase any stale
        # session-scoped absolute path that lives in a SIBLING session dir
        # (e.g. a value persisted as `<campaign>/summaries/20260505/foo`
        # when --session-dir now selects `<campaign>/summaries/20260512`).
        # Without this, switching --session-dir at launch leaves persisted
        # absolute paths pointing at the prior session. Fields the user
        # explicitly overrode via CLI win, so we skip anything already in
        # self.boot_overrides.
        if active_session_dir and "runtime.session_dir" in self.boot_overrides:
            new_base = self._resolve_session_base(active_session_dir)
            if new_base:
                new_base_path = Path(new_base)
                new_sd_parent = str(new_base_path.parent).rstrip("/") + "/"
                new_sd_name = new_base_path.name
                for section, fields in _PATH_FIELDS.items():
                    if section not in ui_raw or not isinstance(ui_raw[section], dict):
                        continue
                    for fname, base in fields.items():
                        if base != "session":
                            continue
                        if f"{section}.{fname}" in self.boot_overrides:
                            continue
                        v = ui_raw[section].get(fname)
                        if not isinstance(v, str) or not v.startswith(new_sd_parent):
                            continue
                        # Path is under the same summaries/ parent; check the
                        # next component. If it's already the active session
                        # name, nothing to do. Otherwise rebase.
                        tail = v[len(new_sd_parent):]
                        sep = tail.find("/")
                        sibling_name = tail if sep == -1 else tail[:sep]
                        if sibling_name == new_sd_name:
                            continue
                        rest = "" if sep == -1 else tail[sep:]
                        ui_raw[section][fname] = new_base + rest

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

    def _resolve_session_base(self, value: str) -> str | None:
        """Resolve a session_dir value (possibly relative) to absolute, without
        the empty/None handling of :meth:`resolve_path`."""
        if not value:
            return None
        p = Path(str(value).strip()).expanduser()
        if not p.is_absolute():
            p = (self.campaign_dir / p)
        return str(p.resolve())


# ── Flat-key overlay for the un-reshaped frontend ──────────────────────────
# The Vue store still reads `config.values.sd_narrate_tokens`, `config.values.
# session_dir`, etc. The route handler builds this projection from the
# resolved view and folds it into the GET /api/config/ response. Removed once
# every frontend view has migrated to `config.resolved`.

_SECTION_TO_PREFIX: dict[str, str] = {
    "session_doc": "sd_",
    "vtt_summary": "vtt_",
    "campaign_state": "cs_",
    "distill": "distill_",
    "party": "party_",
    "planning": "plan_",
    "query": "query_",
    "prep": "prep_",
    "npc": "npc_",
    "workflow": "sw_",
    "connections": "cg_",
}

_EXPERIMENTAL_SUB_TO_PREFIX: dict[str, str] = {
    "narrative": "narr_",
    "enhance_recap": "er_",
    "dnd_sheet": "dnd_",
    "make_tracking": "mt_",
}


def flatten_resolved_to_legacy(resolved: dict[str, Any]) -> dict[str, Any]:
    """Project the service's ``resolved()`` view into the flat-key shape the
    un-reshaped frontend still expects (paths absolute, boot overrides
    applied)."""
    ui = resolved.get("ui", {})
    runtime = resolved.get("runtime", {})
    out: dict[str, Any] = {}

    for section_name, prefix in _SECTION_TO_PREFIX.items():
        section = ui.get(section_name) or {}
        for field, value in section.items():
            if value is None:
                continue
            out[f"{prefix}{field}"] = value

    experimental = ui.get("experimental") or {}
    for sub_name, sub_prefix in _EXPERIMENTAL_SUB_TO_PREFIX.items():
        sub_value = experimental.get(sub_name)
        if isinstance(sub_value, dict):
            for field, value in sub_value.items():
                if value is None:
                    continue
                out[f"{sub_prefix}{field}"] = value

    grounding = ui.get("grounding") or {}
    if grounding.get("summaries") is not None:
        out["summaries"] = grounding["summaries"]

    if runtime.get("session_dir") is not None:
        out["session_dir"] = runtime["session_dir"]
    if runtime.get("default_model") is not None:
        out["global_model"] = runtime["default_model"]

    return out
