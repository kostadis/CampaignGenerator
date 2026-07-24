"""Service owning the Session Doc Editor's configuration slice.

Phase 1 of ``docs/config/session-editor-isolation.md``: the grouped, strict
``SessionEditorConfig`` model exists (``session_editor_config_shared.py``)
and this service exposes the CRUD/resolution API the router will eventually
depend on — but storage is still the platform's ``ui.session_doc`` +
``ui.profiles`` (via the internal adapter below), and the service is **not**
wired into any request path yet. Zero behavior change to the running app.

Phase 5 flips storage to a dedicated ``<config>/session_doc.yaml`` the
service owns exclusively and deletes the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from server.config_models import ProfileEntry
from server.config_service import CampaignConfigService
from server.session_editor_config_shared import (
    Backends,
    EditorPaths,
    NarrateKnobs,
    Roster,
    ScrubKnobs,
    SessionEditorConfig,
)

# ── TEMP — removed in Phase 5 ────────────────────────────────────────────
# Typed `ui.session_doc` field name -> grouped-schema location, expressed as
# a tuple path into the nested SessionEditorConfig shape. This is the
# `_TYPED_TO_CONFIG_KEY`-equivalent for the grouped model; it collapses once
# the service owns `session_doc.yaml` directly and reads/writes the grouped
# shape natively.
#
# Two entries (`anthropic_model` / `claude_code_model`) have no counterpart
# in today's `SessionDocSection` — that flat model was never asked to
# remember an editor-local anthropic/claude-code model override (the
# locked O3 decision is new). They ride along as extra keys absorbed by
# `SessionDocSection`'s `extra="allow"`, purely so a value written through
# `update_config` survives a round trip through the platform store in this
# phase; nothing reads them back out yet (that's Phase 2's O3 work). This
# is a deliberate, minimal addition beyond the phase-1 spec's remap table,
# needed so `update_config({"backends": {"anthropic": {"model": ...}}})`
# doesn't silently drop the value on the next read.
_TYPED_TO_GROUPED: dict[str, tuple[str, ...]] = {
    "session": ("paths", "session_recap"),
    "session_summary": ("paths", "session_summary"),
    "scene_extractions_dir": ("paths", "scene_extractions_dir"),
    "roleplay_dir": ("paths", "roleplay_extractions_dir"),
    "summary_dir": ("paths", "summary_extractions_dir"),
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
    # -- extras, no typed source field (see docstring above) --
    "anthropic_model": ("backends", "anthropic", "model"),
    "claude_code_model": ("backends", "claude_code", "model"),
    # NOTE: the legacy typed `extract_dir` is a dead duplicate of
    # `scene_extractions_dir` (S4 in the design doc) — deliberately not
    # mapped; audited-and-dropped for real in Phase 5.
}
_GROUPED_TO_TYPED: dict[tuple[str, ...], str] = {
    v: k for k, v in _TYPED_TO_GROUPED.items()
}

# session_doc path fields, session-based vs campaign-based, expressed in
# EditorPaths attribute names — mirrors
# CampaignConfigService._PATH_FIELDS["session_doc"] (typed key names) via
# the rename table above.
_SESSION_PATH_FIELDS: tuple[str, ...] = (
    "session_recap",
    "session_summary",
    "scene_extractions_dir",
    "roleplay_extractions_dir",
    "summary_extractions_dir",
    "narration_dir",
    "output_dir",
)
_CAMPAIGN_PATH_FIELDS: tuple[str, ...] = ("party", "voice_dir", "examples_dir")

# ProfileEntry.knobs key -> grouped location, mirrored on activation.
_PROFILE_KNOB_TO_GROUPED: dict[str, tuple[str, ...]] = {
    "narrate_tokens": ("narrate", "tokens"),
    "prose_mode": ("narrate", "prose_mode"),
    "reflections": ("narrate", "reflections"),
    "narration_genre": ("narrate", "genre"),
    "backend": ("backends", "active"),
}


@dataclass(frozen=True)
class ResolvedEditorConfig:
    """Read-only, request-scoped view of :class:`SessionEditorConfig` with
    path fields resolved to absolute and platform extras layered in.

    Never persisted — ``model``/``work_dir``/``campaign_dir``/``config_dir``/
    ``vtt`` are injected read-only context, not stored config. This is the
    contract Phase 2's router `Depends` will consume.
    """

    paths: EditorPaths
    narrate: NarrateKnobs
    scrub: ScrubKnobs
    roster: Roster
    backends: Backends
    session_name: str | None
    profiles: list[ProfileEntry]
    active_profile: str | None
    model: str | None
    work_dir: str
    campaign_dir: str
    config_dir: str
    vtt: str | None = None


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = target
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def _deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``partial`` into ``base``; returns a new dict."""
    out = dict(base)
    for key, value in partial.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class SessionEditorConfigService:
    """Owns the Session Doc Editor's configuration slice.

    Composes a :class:`CampaignConfigService` ("platform") for path
    resolution and platform-owned reads (``runtime.default_model``,
    ``campaign_dir``, ``config_dir``) rather than re-implementing them —
    see ``docs/config/session-editor-isolation.md``'s "ownership boundary".
    """

    def __init__(self, platform: CampaignConfigService) -> None:
        self.platform = platform

    # ── TEMP adapter — removed in Phase 5 ────────────────────────────────

    def _from_platform(self) -> SessionEditorConfig:
        """Read platform storage (``ui.session_doc`` + ``ui.profiles``) and
        map flat typed fields -> the grouped shape."""
        sd = self.platform.ui_state.ui.session_doc.model_dump(mode="json")
        profiles_section = self.platform.ui_state.ui.profiles

        grouped: dict[str, Any] = {}
        for typed_key, target in _TYPED_TO_GROUPED.items():
            if typed_key not in sd:
                continue
            _set_nested(grouped, target, sd[typed_key])

        grouped["profiles"] = [
            p.model_dump(mode="json") for p in profiles_section.profiles
        ]
        grouped["active_profile"] = profiles_section.active

        return SessionEditorConfig.model_validate(grouped)

    def _persist_partial(self, grouped_partial: dict[str, Any]) -> None:
        """Map a grouped partial -> flat typed keys and write through the
        platform's ``session_doc`` / ``profiles`` sections.

        ``profiles`` / ``active_profile`` at the top level route to the
        ``profiles`` section (list-replace semantics); everything else
        routes to ``session_doc`` via the leaf-level rename table.
        """
        flat: dict[str, Any] = {}
        profiles_partial: dict[str, Any] = {}

        def _walk(prefix: tuple[str, ...], node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(prefix + (k,), v)
                return
            typed_key = _GROUPED_TO_TYPED.get(prefix)
            if typed_key is not None:
                flat[typed_key] = node

        for top_key, value in grouped_partial.items():
            if top_key == "profiles":
                profiles_partial["profiles"] = value
                continue
            if top_key == "active_profile":
                profiles_partial["active"] = value
                continue
            _walk((top_key,), value)

        if flat:
            self.platform.update_section("session_doc", flat)
        if profiles_partial:
            self.platform.update_section("profiles", profiles_partial)

    # ── Config ────────────────────────────────────────────────────────

    def get_config(self) -> SessionEditorConfig:
        """Return the stored grouped config. Paths are NOT resolved."""
        return self._from_platform()

    def update_config(self, partial: dict[str, Any]) -> SessionEditorConfig:
        """Merge a grouped, possibly-nested ``partial`` into the stored
        config and persist it.

        ``partial`` may be any subset of the grouped shape, e.g.
        ``{"narrate": {"tokens": 8000}}`` or
        ``{"backends": {"dgx": {"model": "llama"}}}``. Raises
        ``HTTPException(400)`` if the merged result fails schema
        validation (mirrors planning's error contract).
        """
        current = self._from_platform().model_dump(mode="json")
        merged = _deep_merge(current, partial)
        try:
            validated = SessionEditorConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid session editor config: {exc}"
            )
        self._persist_partial(partial)
        return validated

    # ── Profiles ──────────────────────────────────────────────────────

    def list_profiles(self) -> list[ProfileEntry]:
        return list(self.platform.ui_state.ui.profiles.profiles)

    def get_profile(self, name: str) -> ProfileEntry:
        for p in self.list_profiles():
            if p.name == name:
                return p
        raise HTTPException(status_code=404, detail=f"profile '{name}' not found")

    def create_profile(self, entry: ProfileEntry) -> ProfileEntry:
        profiles = self.list_profiles()
        if any(p.name == entry.name for p in profiles):
            raise HTTPException(
                status_code=409, detail=f"profile '{entry.name}' already exists"
            )
        profiles.append(entry)
        self._persist_partial(
            {"profiles": [p.model_dump(mode="json") for p in profiles]}
        )
        return entry

    def update_profile(self, name: str, entry: ProfileEntry) -> ProfileEntry:
        if name != entry.name:
            raise HTTPException(
                status_code=400, detail="profile name mismatch between URL and body"
            )
        profiles = self.list_profiles()
        for i, p in enumerate(profiles):
            if p.name == name:
                profiles[i] = entry
                self._persist_partial(
                    {"profiles": [q.model_dump(mode="json") for q in profiles]}
                )
                return entry
        raise HTTPException(status_code=404, detail=f"profile '{name}' not found")

    def upsert_profile(self, entry: ProfileEntry) -> ProfileEntry:
        """Create-or-replace a profile by name — no 409 on an existing
        name, unlike :meth:`create_profile`."""
        profiles = self.list_profiles()
        for i, p in enumerate(profiles):
            if p.name == entry.name:
                profiles[i] = entry
                break
        else:
            profiles.append(entry)
        self._persist_partial(
            {"profiles": [p.model_dump(mode="json") for p in profiles]}
        )
        return entry

    def delete_profile(self, name: str) -> None:
        profiles = self.list_profiles()
        remaining = [p for p in profiles if p.name != name]
        if len(remaining) == len(profiles):
            raise HTTPException(status_code=404, detail=f"profile '{name}' not found")
        self._persist_partial(
            {"profiles": [p.model_dump(mode="json") for p in remaining]}
        )

    def activate_profile(self, name: str) -> SessionEditorConfig:
        """Copy a profile's narrate/backend knobs into the stored config
        and record it as active (server-side mirror — design decision O2).

        Raises ``HTTPException(404)`` if the profile doesn't exist.
        """
        profile = self.get_profile(name)  # 404 if missing
        partial: dict[str, Any] = {}
        for knob_key, target in _PROFILE_KNOB_TO_GROUPED.items():
            if knob_key in profile.knobs:
                _set_nested(partial, target, profile.knobs[knob_key])
        partial["active_profile"] = name
        return self.update_config(partial)

    # ── Resolved view ─────────────────────────────────────────────────

    def resolved_editor_config(self) -> ResolvedEditorConfig:
        """Grouped config with path fields resolved absolute (delegating to
        ``platform.resolve_path`` per the session/campaign split) plus
        injected, read-only platform extras. Never persisted."""
        cfg = self._from_platform()
        paths_dict = cfg.paths.model_dump(mode="json")
        for f in _SESSION_PATH_FIELDS:
            paths_dict[f] = self.platform.resolve_path(paths_dict.get(f), base="session")
        for f in _CAMPAIGN_PATH_FIELDS:
            paths_dict[f] = self.platform.resolve_path(paths_dict.get(f), base="campaign")
        resolved_paths = EditorPaths.model_validate(paths_dict)

        platform_resolved = self.platform.resolved()
        model = platform_resolved.get("runtime", {}).get("default_model")

        return ResolvedEditorConfig(
            paths=resolved_paths,
            narrate=cfg.narrate,
            scrub=cfg.scrub,
            roster=cfg.roster,
            backends=cfg.backends,
            session_name=cfg.session_name,
            profiles=cfg.profiles,
            active_profile=cfg.active_profile,
            model=model,
            work_dir=str(self.platform.campaign_dir),
            campaign_dir=str(self.platform.campaign_dir),
            config_dir=self.platform.config_dir,
            vtt=None,
        )
