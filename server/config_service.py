"""Residual UI-section configuration service.

Historically this module (as ``CampaignConfigService``) fused two roles:
the permanent platform tier (path resolution, ``runtime.*``, campaign/config
dirs, boot overrides, read-only ``config.yaml``/wiring access) and the
transitional landlord of ten un-isolated ``ui.<section>`` blobs.
``docs/config/platform-isolation.md`` Phase 2 splits them: the platform role
moved to ``server/platform_config_service.py::PlatformConfigService``, and
``UIStateService`` — this class, renamed with no compatibility alias — keeps
only what's left:

    <campaign>/<config-dir>/ui_state.yaml   — tracked, server-owned

``UIStateService`` composes ``PlatformConfigService`` (constructor-injected,
mirroring ``SessionEditorConfigService``/``PlanningConfigService``'s existing
shape) for everything platform-owned: ``campaign_dir``/``config_dir``/
``config_path_base``, ``resolve_path``/``relativize_path``, and (in
``resolved()``) ``boot_overrides``/``local``. It never re-derives any of
those.

As of Phase 3 (O3), that composition now also covers ``runtime``:
``runtime.{default_model, session_dir}`` moved out of ``ui_state.yaml`` into
its own ``<config>/platform.yaml`` that ``PlatformConfigService`` owns
outright (see that class's module docstring). ``UIStateService`` no longer
stores ``runtime`` at all — ``UIState`` dropped the field entirely — and
reads it exclusively through ``self.platform.runtime`` wherever it used to
read ``self._ui_state.runtime`` (the load-time normalize pass in
``_normalize_stored_paths`` and the read view in ``resolved()``). There is
no more write-delegation the other direction either: ``PlatformConfigService.
update_runtime`` writes ``platform.yaml`` directly now, and the
``update_runtime`` method that used to live on THIS class is gone.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from server.config_models import UI_SECTION_NAMES, UIState

if TYPE_CHECKING:
    from server.platform_config_service import PlatformConfigService

# ── Filenames ──────────────────────────────────────────────────────────────

UI_STATE_NAME = "ui_state.yaml"

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

# EMPTY as of Phase 10 of docs/config/grounding-isolation.md. `grounding.
# summaries` was its last row, and it left with the other four grounding
# sections for <config>/grounding.yaml.
#
# Deliberately kept rather than deleted, and deliberately flagged rather than
# left to look load-bearing: the normalization/relativization machinery below
# still runs, it just has no rows to act on. Retiring it belongs with retiring
# UIStateService itself — the next isolation that empties UISection — not with
# this one. A table that silently does nothing is exactly how
# `derive_campaign_paths` drifted (see docs/config/schema.md's "Path resolution
# base"), so if you are here because you added a `ui.<section>` path field:
# add its row, don't work around the emptiness.
_PATH_FIELDS: dict[str, dict[str, str]] = {}

# session_dir is itself a campaign-based path (it lives under
# <campaign>/summaries/..., so it resolves against the campaign root, not
# against itself). Consumed inside resolved() below to path-resolve the
# runtime slice the same way _PATH_FIELDS resolves ui.<section> — the
# knowledge stays here (rather than moving to platform_config_service.py
# alongside runtime's storage) because resolved() is the only consumer and
# already owns the sibling _PATH_FIELDS table it's applied alongside.
_RUNTIME_PATH_FIELDS: dict[str, str] = {"session_dir": "campaign"}


# ── Errors ─────────────────────────────────────────────────────────────────


class ConfigError(RuntimeError):
    """Raised at startup when a required config file is missing or malformed."""


# ── Service ────────────────────────────────────────────────────────────────


class UIStateService:
    """Owns ``ui_state.yaml`` — the ten un-isolated ``ui.<section>`` blobs
    plus the ``runtime`` key physically stored alongside them (see module
    docstring for why the latter is still here).

    One instance per server process, held as ``PlatformConfigService.uis``
    (constructed internally — see that class). Routers reach it through
    ``request.app.state.platform.uis``. Concurrent ``update_section`` calls
    on different sections are independent; concurrent calls on the same
    section are serialized by ``self._write_lock`` so writes are last-writer-
    wins per section but never produce a torn file.
    """

    def __init__(self, platform: "PlatformConfigService") -> None:
        self.platform = platform
        self._write_lock = threading.Lock()

        self._ui_state: UIState = self._load_ui_state()
        self._normalize_stored_paths()

    # ── Path properties ────────────────────────────────────────────────

    @property
    def ui_state_path(self) -> Path:
        return self.platform.config_path_base / UI_STATE_NAME

    # ── Loaders ────────────────────────────────────────────────────────

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

    def _normalize_stored_paths(self) -> None:
        """One-time load-time self-heal for pre-existing ``ui_state.yaml``
        files written before the write-time relativization choke point in
        :meth:`update_section` existed.

        Rewrites absolute ``grounding`` path fields to relative storage when
        they already sit under the applicable base, using the CURRENTLY
        PERSISTED ``runtime.session_dir`` (not any boot override) as the
        session base. Session-scoped fields are left untouched when
        ``runtime.session_dir`` is unset — same guard as
        :meth:`PlatformConfigService.relativize_path` itself, for the same
        reason: there is no base to relativize against yet.
        Persists only if at least one field actually changed.

        Reads ``self.platform.runtime.session_dir`` rather than a field on
        ``self._ui_state`` (Phase 3, O3: ``runtime`` no longer lives in
        ``ui_state.yaml`` at all). This is exactly why
        ``PlatformConfigService.__init__`` loads ``platform.yaml`` BEFORE
        constructing this service — see that class's docstring — otherwise
        this read would see stale/default runtime data instead of the real
        persisted session dir.
        """
        sections_to_check = ("grounding",)
        persisted_session_dir = self.platform.runtime.session_dir

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
                new_value = self.platform.relativize_path(
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
                    to_store[field] = self.platform.relativize_path(
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

    # ── Read views ──────────────────────────────────────────────────────

    @property
    def ui_state(self) -> UIState:
        return self._ui_state

    def resolved(self) -> dict[str, Any]:
        """Typed read view with paths resolved (per-field base) and boot
        overrides applied. Returned as plain dicts for JSON friendliness.

        Still the fused ``{campaign_dir, ui, runtime, server, nav}`` shape
        the old ``CampaignConfigService.resolved()`` returned — kept here
        after Phase 3 too (docs/config/platform-isolation.md's "hard design
        question", resolved in favor of minimal churn: this method already
        needs ``_PATH_FIELDS`` knowledge for the ``ui.<section>`` resolution
        and the sibling-session rebase, so moving just ``runtime``'s source
        was the smaller change). ``runtime``/``server``/``nav`` are now ALL
        platform-owned data, read through ``self.platform.runtime`` /
        ``self.platform.local`` rather than fields this class stores itself
        — as of Phase 3, this class stores none of the three.
        """
        ui_raw = self._ui_state.ui.model_dump(mode="json")
        runtime_raw = self.platform.runtime.model_dump(mode="json")
        local_raw = self.platform.local.model_dump(mode="json")

        # Boot overrides must be applied to the path-resolution context BEFORE
        # we resolve session-relative paths — otherwise an override of
        # runtime.session_dir wouldn't change where session-scoped paths land.
        # We apply overrides into the raw dicts first, then resolve.
        for key, value in self.platform.boot_overrides.items():
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
        # self.platform.boot_overrides.
        if active_session_dir and "runtime.session_dir" in self.platform.boot_overrides:
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
                        if f"{section}.{fname}" in self.platform.boot_overrides:
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
                    ui_raw[section][fname] = self.platform.resolve_path(
                        ui_raw[section][fname],
                        base=base,
                        session_dir=active_session_dir,
                    )

        for fname, base in _RUNTIME_PATH_FIELDS.items():
            if fname in runtime_raw:
                runtime_raw[fname] = self.platform.resolve_path(
                    runtime_raw[fname], base=base,
                )

        return {
            "campaign_dir": str(self.platform.campaign_dir),
            "ui": ui_raw,
            "runtime": runtime_raw,
            "server": local_raw.get("server", {}),
            "nav": local_raw.get("nav", {}),
        }

    def _resolve_session_base(self, value: str) -> str | None:
        """Resolve a session_dir value (possibly relative) to absolute, without
        the empty/None handling of :meth:`PlatformConfigService.resolve_path`."""
        if not value:
            return None
        p = Path(str(value).strip()).expanduser()
        if not p.is_absolute():
            p = (self.platform.campaign_dir / p)
        return str(p.resolve())
