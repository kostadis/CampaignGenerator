"""Service owning the Session Doc Editor's configuration slice.

Phase 5 of ``docs/config/session-editor-isolation.md``: storage is a
dedicated ``<config>/session_doc.yaml`` this service owns exclusively —
``ui_state.yaml`` is never touched by an editor write. The service still
composes the platform (:class:`~server.platform_config_service.
PlatformConfigService`, per ``docs/config/platform-isolation.md`` Phase 2 —
formerly ``CampaignConfigService``) for path resolution and platform-owned
reads (``runtime.default_model``, ``runtime.session_dir``, ``campaign_dir``,
``config_dir``) rather than re-implementing them — see that design doc's
"ownership boundary".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from server.session_editor_config_shared import ProfileEntry
from server.session_editor_config_shared import (
    Backends,
    EditorPaths,
    ExtractKnobs,
    NarrateKnobs,
    SessionEditorConfig,
    load_session_editor_config,
    save_session_editor_config,
)

if TYPE_CHECKING:
    from server.platform_config_service import PlatformConfigService

SESSION_DOC_FILENAME = "session_doc.yaml"

# session_doc path fields, session-based vs campaign-based, expressed in
# EditorPaths attribute names — the service-owned metadata described in
# session_editor_config_shared.EditorPaths's docstring.
_SESSION_PATH_FIELDS: tuple[str, ...] = (
    "session_recap",
    "session_summary",
    "scene_extractions_dir",
    "narration_dir",
    "output_dir",
)
_CAMPAIGN_PATH_FIELDS: tuple[str, ...] = (
    "party", "voice_dir", "examples_dir", "genre_file",
)

# ProfileEntry.knobs key -> grouped location, mirrored on activation.
_PROFILE_KNOB_TO_GROUPED: dict[str, tuple[str, ...]] = {
    "narrate_tokens": ("narrate", "tokens"),
    "prose_mode": ("narrate", "prose_mode"),
    "reflections": ("narrate", "reflections"),
    # A profile switches which rulebook *file* is used, never a copy of its
    # text (#276 fix 2). The old ``narration_genre`` knob held a paste of a
    # paste: profile -> narrate.genre -> voice/_genre.md, synced one way only
    # (#220), so activating a profile could silently overwrite a hand-edit
    # with a stale duplicate.
    "narration_genre_file": ("paths", "genre_file"),
    "backend": ("backends", "active"),
}


@dataclass(frozen=True)
class ResolvedGenre:
    """Read-only view of the genre rulebook file, for display only.

    The Session Doc Editor shows the path, whether it resolved, and enough of
    the content to recognise it — it does not offer to edit it. The file is
    hand-authored campaign material; a browser textarea is what flattened
    out-of-the-abyss' 88 lines into a single 16,303-character line (#249/#276).

    ``text`` is deliberately **not** included: nothing downstream should read
    the rulebook from this view. Pass 5 reads the file itself, by path.
    """

    path: str | None
    exists: bool
    lines: int = 0
    chars: int = 0
    preview: str = ""
    sha256: str = ""
    error: str | None = None


_GENRE_PREVIEW_CHARS = 600


def _describe_genre_file(resolved_path: str | None) -> ResolvedGenre:
    """Summarise the resolved genre file without letting its text escape."""
    if not resolved_path:
        return ResolvedGenre(path=None, exists=False)
    p = Path(resolved_path)
    if not p.is_file():
        return ResolvedGenre(
            path=resolved_path,
            exists=False,
            error=(
                "file not found — Pass 5 will run with no genre directive"
            ),
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ResolvedGenre(
            path=resolved_path, exists=False, error=f"unreadable: {exc}"
        )
    stripped = text.strip()
    return ResolvedGenre(
        path=resolved_path,
        exists=True,
        lines=len(stripped.splitlines()),
        chars=len(stripped),
        preview=stripped[:_GENRE_PREVIEW_CHARS],
        # Provenance for the per-run knobs snapshot: two runs used the same
        # rulebook iff these match, and a file edited between runs is visible
        # without storing 16K of prose in every per-scene sidecar.
        sha256=hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:12],
    )


@dataclass(frozen=True)
class ResolvedEditorConfig:
    """Read-only, request-scoped view of :class:`SessionEditorConfig` with
    path fields resolved to absolute and platform extras layered in.

    Never persisted — ``model``/``work_dir``/``campaign_dir``/``config_dir``/
    ``vtt`` are injected read-only context, not stored config.
    """

    paths: EditorPaths
    extract: ExtractKnobs
    narrate: NarrateKnobs
    backends: Backends
    session_name: str | None
    profiles: list[ProfileEntry]
    active_profile: str | None
    model: str | None
    work_dir: str
    campaign_dir: str
    config_dir: str
    vtt: str | None = None
    session_dir: str | None = None
    # Display-only summary of paths.genre_file (#276 fix 2). Injected, never
    # persisted — same class of read-only extra as ``model``/``work_dir``.
    genre: ResolvedGenre | None = None
    # The resolved default per DM-18 steps 2-3 (config pin, else the backend
    # default), for the UI's initial checkbox state (DM-20). Injected, never
    # persisted — same class of read-only extra as ``model``/``work_dir``.
    # Deliberately NOT under ``extract``: that field IS the persisted
    # ``ExtractKnobs`` model (``extra="forbid"``), so a derived field there
    # would become known, stored and PUT-able — the opposite of read-only.
    # Step 1 of DM-18 (an explicit per-run query-param choice) is NOT folded
    # in here — this value is computed with no request in scope, so a route
    # applies step 1 on top of it.
    batch_scenes_effective: bool = False


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


def _canonicalize_backend_aliases(partial: dict[str, Any]) -> dict[str, Any]:
    """Normalize YAML backend aliases before merging a partial update.

    ``model_dump()`` uses Python field names for the merge base, while the
    editor wire/YAML shape uses ``claude-code`` and ``codex-cli``.  Translate
    only those field aliases at this boundary so old Python-name callers and
    canonical UI/YAML callers both update the same profile.  The stored
    representation is still emitted by ``save_session_editor_config`` with
    aliases enabled.
    """
    raw_backends = partial.get("backends")
    if not isinstance(raw_backends, dict):
        return partial

    backends = dict(raw_backends)
    for alias, field_name in (
        ("claude-code", "claude_code"),
        ("codex-cli", "codex_cli"),
    ):
        if alias not in backends:
            continue
        alias_value = backends.pop(alias)
        existing_value = backends.get(field_name)
        if isinstance(alias_value, dict) and isinstance(existing_value, dict):
            backends[field_name] = _deep_merge(alias_value, existing_value)
        elif field_name not in backends:
            backends[field_name] = alias_value

    normalized = dict(partial)
    normalized["backends"] = backends
    return normalized


class SessionEditorConfigService:
    """Owns the Session Doc Editor's configuration slice.

    Storage is a dedicated ``<config>/session_doc.yaml`` (see
    :attr:`session_doc_path`) — a bad write here cannot corrupt
    ``ui_state.yaml``. Composes a :class:`~server.platform_config_service.
    PlatformConfigService` ("platform") for path resolution and
    platform-owned reads rather than re-implementing them — see
    ``docs/config/session-editor-isolation.md``'s "ownership boundary".
    """

    def __init__(self, platform: "PlatformConfigService") -> None:
        self.platform = platform

    @property
    def session_doc_path(self) -> Path:
        return self.platform.config_path_base / SESSION_DOC_FILENAME

    # ── Path relativization (write-time choke point) ────────────────────
    # The frontend sends absolute paths (it calls resolvePath client-side).
    # Mirrors UIStateService.update_section's write-time relativize_path
    # call, so session-scoped fields re-point when runtime.session_dir
    # changes later — see relativize_path's docstring for why a stale
    # absolute value would otherwise stick. Keyed off the PERSISTED
    # runtime.session_dir only (self.platform.runtime, not
    # resolved()/boot_overrides) — mirrors the persisted-only rule in
    # UIStateService._normalize_stored_paths, for the same reason: a
    # boot-override session_dir is process-lifetime-only and must never be
    # baked into on-disk relative storage.

    def _relativized_paths(self, paths: EditorPaths) -> EditorPaths:
        session_dir = self.platform.runtime.session_dir
        paths_dict = paths.model_dump(mode="json")
        for f in _SESSION_PATH_FIELDS:
            paths_dict[f] = self.platform.relativize_path(
                paths_dict.get(f), base="session", session_dir=session_dir
            )
        for f in _CAMPAIGN_PATH_FIELDS:
            paths_dict[f] = self.platform.relativize_path(
                paths_dict.get(f), base="campaign"
            )
        return EditorPaths.model_validate(paths_dict)

    def _save(self, cfg: SessionEditorConfig) -> SessionEditorConfig:
        to_store = cfg.model_copy(
            update={"paths": self._relativized_paths(cfg.paths)}
        )
        save_session_editor_config(self.session_doc_path, to_store)
        return cfg

    # ── Config ────────────────────────────────────────────────────────

    def get_config(self) -> SessionEditorConfig:
        """Return the stored grouped config. Paths are NOT resolved."""
        return load_session_editor_config(self.session_doc_path)

    def update_config(self, partial: dict[str, Any]) -> SessionEditorConfig:
        """Merge a grouped, possibly-nested ``partial`` into the stored
        config and persist it to ``session_doc.yaml``.

        ``partial`` may be any subset of the grouped shape, e.g.
        ``{"narrate": {"tokens": 8000}}`` or
        ``{"backends": {"dgx": {"model": "llama"}}}``. Raises
        ``HTTPException(400)`` if the merged result fails schema
        validation. Path fields are relativized (write-time choke point,
        see :meth:`_relativized_paths`) before the write; the value
        returned to the caller is the validated, UN-relativized config
        (whatever paths were passed in), mirroring the old adapter's
        contract.
        """
        current = self.get_config().model_dump(mode="json")
        merged = _deep_merge(current, _canonicalize_backend_aliases(partial))
        try:
            validated = SessionEditorConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid session editor config: {exc}"
            )
        self._save(validated)
        return validated

    # ── Profiles ──────────────────────────────────────────────────────

    def list_profiles(self) -> list[ProfileEntry]:
        return list(self.get_config().profiles)

    def get_profile(self, name: str) -> ProfileEntry:
        for p in self.list_profiles():
            if p.name == name:
                return p
        raise HTTPException(status_code=404, detail=f"profile '{name}' not found")

    def create_profile(self, entry: ProfileEntry) -> ProfileEntry:
        cfg = self.get_config()
        if any(p.name == entry.name for p in cfg.profiles):
            raise HTTPException(
                status_code=409, detail=f"profile '{entry.name}' already exists"
            )
        self._save(cfg.model_copy(update={"profiles": [*cfg.profiles, entry]}))
        return entry

    def update_profile(self, name: str, entry: ProfileEntry) -> ProfileEntry:
        if name != entry.name:
            raise HTTPException(
                status_code=400, detail="profile name mismatch between URL and body"
            )
        cfg = self.get_config()
        profiles = list(cfg.profiles)
        for i, p in enumerate(profiles):
            if p.name == name:
                profiles[i] = entry
                self._save(cfg.model_copy(update={"profiles": profiles}))
                return entry
        raise HTTPException(status_code=404, detail=f"profile '{name}' not found")

    def upsert_profile(self, entry: ProfileEntry) -> ProfileEntry:
        """Create-or-replace a profile by name — no 409 on an existing
        name, unlike :meth:`create_profile`."""
        cfg = self.get_config()
        profiles = list(cfg.profiles)
        for i, p in enumerate(profiles):
            if p.name == entry.name:
                profiles[i] = entry
                break
        else:
            profiles.append(entry)
        self._save(cfg.model_copy(update={"profiles": profiles}))
        return entry

    def delete_profile(self, name: str) -> None:
        cfg = self.get_config()
        remaining = [p for p in cfg.profiles if p.name != name]
        if len(remaining) == len(cfg.profiles):
            raise HTTPException(status_code=404, detail=f"profile '{name}' not found")
        self._save(cfg.model_copy(update={"profiles": remaining}))

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
        injected, read-only platform extras. Never persisted.

        ``runtime.session_dir`` is read once from ``platform.resolved()``
        (which already folds in any ``--session-dir`` boot override — see
        ``main._boot_overrides_from_args``) and threaded explicitly into
        every session-based ``resolve_path`` call below. Without this, a
        relative session-scoped field (e.g. a persisted
        ``scene_extractions_dir``) would resolve against the *persisted*
        ``runtime.session_dir`` instead of a boot-override one, since
        ``resolve_path`` falls back to the persisted value when no
        ``session_dir`` argument is given. This is the "one derivation" the
        Phase 4 boot unification promises: the boot override reaches this
        service's path resolution the same way it reaches
        ``UIStateService.resolved()`` (via ``PlatformConfigService.
        resolved()``, which delegates to it), with no second, independent
        derivation of session paths anywhere else.
        """
        platform_resolved = self.platform.resolved()
        model = platform_resolved.get("runtime", {}).get("default_model")
        session_dir = platform_resolved.get("runtime", {}).get("session_dir")

        cfg = self.get_config()
        paths_dict = cfg.paths.model_dump(mode="json")
        for f in _SESSION_PATH_FIELDS:
            paths_dict[f] = self.platform.resolve_path(
                paths_dict.get(f), base="session", session_dir=session_dir
            )
        for f in _CAMPAIGN_PATH_FIELDS:
            paths_dict[f] = self.platform.resolve_path(paths_dict.get(f), base="campaign")
        resolved_paths = EditorPaths.model_validate(paths_dict)

        # DM-18 steps 2-3: an explicit config pin wins; otherwise the backend
        # default is `True` on the subscription backends (Claude Code and
        # Codex CLI have no prompt caching, so one batched call beats N
        # sequential per-scene calls) and `False` elsewhere. Step 1 (an
        # explicit per-run choice) has no request to consult here — it is
        # applied by the route on top of this value.
        batch_scenes_effective = (
            cfg.extract.batch_scenes
            if cfg.extract.batch_scenes is not None
            else cfg.backends.active in ("claude-code", "codex-cli")
        )

        return ResolvedEditorConfig(
            paths=resolved_paths,
            extract=cfg.extract,
            narrate=cfg.narrate,
            backends=cfg.backends,
            session_name=cfg.session_name,
            profiles=cfg.profiles,
            active_profile=cfg.active_profile,
            model=model,
            work_dir=str(self.platform.campaign_dir),
            campaign_dir=str(self.platform.campaign_dir),
            config_dir=self.platform.config_dir,
            vtt=None,
            session_dir=session_dir,
            genre=_describe_genre_file(resolved_paths.genre_file),
            batch_scenes_effective=batch_scenes_effective,
        )
