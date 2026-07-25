"""Service owning the permanent platform tier.

``docs/config/platform-isolation.md`` split the old ``CampaignConfigService``
(610 lines) into two roles that were previously fused: the permanent
**platform** — path resolution, ``campaign_dir``/``config_dir``, boot
overrides, the read-only ``config.yaml``/wiring view, and (as of Phase 3, O3)
``runtime.{default_model, session_dir}`` outright — and the transitional
**residual landlord** of the un-isolated ``ui.<section>`` blobs, which kept
the (renamed, no-alias) ``UIStateService``.

**The residual half no longer exists.** ``docs/config/ui-state-retirement.md``
retired ``UIStateService``, ``ui_state.yaml`` and the six loose sections it
held: they were empty in every campaign and had no writer — the generic
``PUT /api/config/section/{name}`` route that was their only write door had no
client. This class is what the split was always converging on: one object,
one role, owning every value it serves.

``PlatformConfigService`` resolves and validates ``campaign_dir``, creates
``config_path_base``, and loads three documents — the human-owned
``config.yaml`` (``tracked``), the machine-local
``.campaigngenerator.local.yaml`` (``local``), and its own
``<config>/platform.yaml`` (``runtime``). Every per-service config service
(``SessionEditorConfigService``, ``PlanningConfigService``,
``EnsembleConfigService``, ``GroundingConfigService``, ``PartyConfigService``)
composes it — one platform, several tenants.

## Construction order is no longer load-bearing

Two coupling hazards used to live here and are both gone with the tenant that
created them.

``platform.yaml`` had to load BEFORE ``UIStateService`` was constructed,
because that class's ``_normalize_stored_paths`` relativized ``ui.*`` path
fields against the currently persisted ``runtime.session_dir`` — a value
living in a different document from the one being constructed. Loading in the
wrong order would have silently re-anchored session-scoped paths rather than
erroring.

Earlier still, ``resolve_path``/``relativize_path``'s ``base="session"``
fallback read ``self.uis.ui_state.runtime.session_dir`` — data owned by the
object under construction — so that branch had to stay provably unreachable
during ``UIStateService.__init__``. Phase 3 of the platform isolation
dissolved that by pointing the fallback at ``self._doc.runtime.session_dir``.

Both notes are kept as history rather than deleted outright: they explain why
``self._doc`` is still assigned last among the three loaded documents, and
they are the reason to think twice before adding a new tenant that reads
platform state during its own construction.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, Request
from pydantic import ValidationError

from campaignlib import DEFAULT_MODEL
from campaignlib.constants import config_path
from campaignlib.party_config import PARTY_CONFIG_FILENAME
from server.platform_config_shared import (
    LOCAL_CONFIG_NAME,
    PLATFORM_CONFIG_NAME,
    ConfigError,
    PlatformConfig,
    PlatformDocument,
    PlatformLocalConfig,
    PlatformRuntime,
    load_local_config,
    load_platform_config,
    save_local_config,
    save_platform_config,
)

# ── Filenames ──────────────────────────────────────────────────────────────

TRACKED_CONFIG_NAME = "config.yaml"

# ── Boot-override targets ──────────────────────────────────────────────────
# The dotted-key sections :meth:`PlatformConfigService.resolved` knows how to
# apply. An override aimed anywhere else reaches no consumer — and per O1 of
# ``docs/config/platform-isolation.md`` a boot flag that reaches no consumer is
# a defect, not a no-op. So an unknown section is a ``ConfigError`` at
# construction rather than a value silently dropped at read time.
#
# This closes the assertion gap that let twelve dead ``session_doc.*`` flags
# survive unnoticed: ``resolved()`` used to have an ``else`` branch that swept
# any unrecognised section into ``ui_raw``, where nothing ever read it. That
# branch went with ``ui_raw`` itself (docs/config/ui-state-retirement.md); it is
# replaced by this check rather than by nothing, so the next dead flag fails
# loudly at boot instead of being quietly absorbed.
_BOOT_OVERRIDE_SECTIONS: tuple[str, ...] = ("runtime", "server")

# session_dir is itself a campaign-based path (it lives under
# <campaign>/summaries/...), so it resolves against the campaign root, not
# against itself. Applied in resolved() below.
_RUNTIME_PATH_FIELDS: dict[str, str] = {"session_dir": "campaign"}


def require_platform(request: Request) -> "PlatformConfigService":
    """Fetch this process's ``PlatformConfigService`` from ``app.state.platform``,
    or raise ``503`` if the server booted without a resolved ``campaign_dir``.

    Every router that needs the platform used to duplicate this same
    "getattr, then raise if missing" check independently. Before Phase 4
    (``docs/config/platform-isolation.md``) there were at least three
    copies: ``config_routes._require_service`` (the canonical one, per its
    own docstring), ``planning_routes.get_planning_service``'s inline
    block, and ``server/config.py``'s ``get_campaign_dir_from_request`` —
    whose own docstring admitted it "mirrors the pattern used in
    ``config_routes._require_service``" rather than sharing it. This
    function is the one implementation; ``config_routes.py`` and
    ``planning_routes.py`` both call it now instead of restating the
    ``getattr(..., "platform", None)`` + 503 branch.

    (``scene_editor.get_editor_service`` and ``grounding._backend_flags``
    carry two more copies of the same shape. Not folded here — out of
    Phase 4's named scope — but a candidate for the same treatment later.)

    Returns the live service object, not just ``campaign_dir``, since every
    known caller needs the object anyway (to construct a per-page service,
    or to call a method on it) and a bare string would just be re-derived
    from ``platform.campaign_dir`` a line later.
    """
    platform = getattr(request.app.state, "platform", None)
    if platform is None:
        raise HTTPException(
            status_code=503,
            detail="config service not initialized — campaign_dir not resolved at boot",
        )
    return platform


def resolve_default_model(model: str | None, request: Request) -> str:
    """Resolve the ``--model`` a subprocess run should use, per the
    precedence table in ``docs/config/platform-isolation.md``'s "Model
    resolution precedence (O4)" (the first three of its six levels; levels
    4–6 collapse into a single "platform or literal" step here since Phase
    5a does not touch backend-remembered-model or wiring):

    1. An explicit ``model`` — the per-run value a request actually supplied
       (the frontend forwards the sidebar's pick here; a caller that omits
       it wants the platform default, not this function's opinion).
    2. ``runtime.default_model`` — the platform's persisted sidebar pick
       (``PlatformConfigService.runtime.default_model``, see
       ``platform_config_shared.PlatformRuntime``).
    3. ``campaignlib.constants.DEFAULT_MODEL`` — the literal fallback, used
       only if ``runtime.default_model`` is somehow falsy (it has a
       ``default_factory`` that itself resolves to this same literal, so
       this branch should be unreachable in practice) or if no live
       ``PlatformConfigService`` exists for this request at all.

    This is the fix for the bug the design doc's Phase 5a exists to close:
    twelve router request-body fields independently hardcoded
    ``model: str = "claude-sonnet-4-6"`` as their FastAPI default, so a
    request that omitted ``model`` silently got that literal instead of
    ``runtime.default_model`` — the sidebar model picker was bypassed on
    every one of those paths. Callers now declare ``model: str | None =
    None`` and call this function instead of hardcoding a default.

    The "no live platform" branch (``require_platform`` raising) is caught
    rather than left to propagate as a 503: on a normally booted server this
    can't happen (``server/main.py`` refuses to boot without resolving
    ``app.state.platform``), so this is defense for a request handled
    outside that lifecycle — mirroring ``grounding.py``'s ``_backend_flags``,
    which treats a missing platform as "no overrides" for the exact same
    reason rather than erroring. Silently returning the literal is safe
    specifically because the caller already asked for the platform's value
    and got "no platform to ask", not "a value the platform doesn't want" —
    it is not the shortcut the design doc's Phase 5a warns against (which is
    hardcoding this literal as the FastAPI field default *instead of* ever
    asking the platform, which is what this function replaces).
    """
    if model:
        return model
    try:
        platform = require_platform(request)
    except HTTPException:
        return DEFAULT_MODEL
    return platform.runtime.default_model or DEFAULT_MODEL


class PlatformConfigService:
    """Owns the platform tier for a single campaign workspace.

    One instance per server process, held as ``app.state.platform`` — the
    canonical handle (there is no ``app.state.config_service`` any more, and
    no ``self.uis`` sub-service: see the module docstring).
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

        # Fail loudly on an override with no consumer — see
        # _BOOT_OVERRIDE_SECTIONS for why this is a raise and not a drop.
        for key in self.boot_overrides:
            section, dot, _ = key.partition(".")
            if dot and section not in _BOOT_OVERRIDE_SECTIONS:
                raise ConfigError(
                    f"boot override {key!r} targets unknown section {section!r}; "
                    f"valid sections: {', '.join(_BOOT_OVERRIDE_SECTIONS)}"
                )

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
        self._doc: PlatformDocument = self._load_platform_doc()

    # ── Path properties ────────────────────────────────────────────────

    @property
    def config_path(self) -> Path:
        return self.config_path_base / TRACKED_CONFIG_NAME

    @property
    def local_config_path(self) -> Path:
        return self.config_path_base / LOCAL_CONFIG_NAME

    @property
    def platform_config_path(self) -> Path:
        return self.config_path_base / PLATFORM_CONFIG_NAME

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

    def _load_platform_doc(self) -> PlatformDocument:
        """Load ``platform.yaml``, converting the shared loader's
        ``ValueError``/``ValidationError`` into ``ConfigError`` so a
        construction-time failure surfaces through the one error type
        ``server/main.py`` already catches and reports — same treatment
        ``_load_tracked`` and ``UIStateService._load_ui_state`` give their
        own documents. See ``load_platform_config``'s docstring for why this
        file is NOT warn-and-drop like the local config."""
        try:
            return load_platform_config(self.platform_config_path)
        except (ValueError, ValidationError) as exc:
            raise ConfigError(
                f"{PLATFORM_CONFIG_NAME} failed to load: {exc}"
            ) from exc

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
        """Current PERSISTED runtime values, read straight from this
        service's own in-memory copy of ``platform.yaml`` — no delegation,
        as of Phase 3 (O3)."""
        return self._doc.runtime

    @property
    def wiring(self) -> dict:
        """External, mneme-rendered wiring (``config/wiring.yaml``) — see
        ``campaignlib.wiring``. Returns ``{}`` when no rendered file is
        found (e.g. this machine, per the design doc's "Risks" section);
        callers must treat that as "nothing configured", not an error."""
        from campaignlib.wiring import load_wiring

        return load_wiring()

    def snapshot(self) -> PlatformConfig:
        """A single strict, validated view combining ``runtime`` (from
        ``platform.yaml``) and ``local``'s ``server``/``nav`` (from
        ``.campaigngenerator.local.yaml``) — assembled fresh from today's
        two stores. See ``PlatformConfig``'s docstring for why this spans
        two files rather than being one document's literal shape."""
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
        """Merge ``partial`` into ``runtime`` and persist atomically to
        ``platform.yaml`` — owned outright as of Phase 3 (O3), no delegation
        to ``UIStateService``. Used by the sidebar model picker
        (``default_model``) and SessionConfig (``session_dir``). Guarded by
        the same ``self._write_lock`` as ``update_local``: two independent
        files, one lock, matching the pre-Phase-3 shape where a single lock
        already covered unrelated writers on this class.
        """
        with self._write_lock:
            current = self._doc.runtime.model_dump(mode="json")
            current.update(partial)
            new_runtime = PlatformRuntime.model_validate(current)
            new_doc = self._doc.model_copy(update={"runtime": new_runtime})
            save_platform_config(self.platform_config_path, new_doc)
            self._doc = new_doc
        return new_runtime

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
        When omitted, the value falls back to this service's own persisted
        ``platform.yaml`` (``self._doc.runtime.session_dir``) — platform-local
        state, so this fallback carries no construction-order hazard (see
        class docstring).
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
            sd = session_dir or self._doc.runtime.session_dir
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
            sd = session_dir or self._doc.runtime.session_dir
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

    # ── Combined resolved view ──────────────────────────────────────────

    def resolved(self) -> dict[str, Any]:
        """The combined ``{campaign_dir, runtime, server, nav}`` read view —
        boot overrides applied on top of persisted values, path fields
        absolute. Returned as plain dicts for JSON friendliness.

        **The ``ui`` key is gone** (docs/config/ui-state-retirement.md). It
        carried the six loose ``ui.<section>`` blobs, all of which were empty
        in every campaign and unreachable-by-write from the shipped UI —
        ``PUT /api/config/section/{name}`` had no client. Three frontend sites
        read keys off it; all three read sections that no longer existed or
        had never been written, and all three now read the owning service's
        own document instead. The four keys below are the live ones — see the
        design doc's "resolved() is still needed" table for each one's
        consumers.

        This method lived on ``UIStateService`` through the platform
        isolation, on the reasoning that it needed that class's
        ``_PATH_FIELDS`` knowledge for the ``ui.<section>`` resolution and the
        sibling-session rebase. Both went with the ``ui`` key:
        ``_PATH_FIELDS`` had been empty since Phase 10 of the grounding
        isolation, so the rebase loop and the per-field resolution were
        iterating an empty table. What is left needs nothing ``UIStateService``
        owned, so it comes home to the object that owns every value in it.
        """
        runtime_raw = self.runtime.model_dump(mode="json")
        local_raw = self._local.model_dump(mode="json")

        # Boot overrides apply BEFORE path resolution — an override of
        # runtime.session_dir has to be in place before anything resolves
        # against it. Unknown dotted sections cannot reach here: __init__
        # rejects them (see _BOOT_OVERRIDE_SECTIONS).
        for key, value in self.boot_overrides.items():
            section, dot, field = key.partition(".")
            if not dot:
                runtime_raw[key] = value
            elif section == "runtime":
                runtime_raw[field] = value
            else:  # "server"
                local_raw.setdefault("server", {})[field] = value

        for fname, base in _RUNTIME_PATH_FIELDS.items():
            if fname in runtime_raw:
                runtime_raw[fname] = self.resolve_path(runtime_raw[fname], base=base)

        return {
            "campaign_dir": str(self.campaign_dir),
            "runtime": runtime_raw,
            "server": local_raw.get("server", {}),
            "nav": local_raw.get("nav", {}),
        }

    # ── Filesystem discovery (O2) ────────────────────────────────────────

    @staticmethod
    def discover_campaign_paths(campaign_dir: str, session_dir: str) -> dict[str, str]:
        """Probe the filesystem for files whose name or presence cannot be
        known in advance — the sole surviving half of the old
        ``server/config.py::derive_campaign_paths`` (O2,
        ``docs/config/platform-isolation.md``). Backs
        ``GET /api/config/campaign-paths``, whose only caller is
        ``SessionConfig.vue``'s ``deriveAll()`` on the first screen a GM
        sees, before ``session_dir`` is even persisted — hence a
        ``@staticmethod`` rather than an instance method: there may be no
        live ``PlatformConfigService`` for this ``campaign_dir`` yet.

        The deleted half was **derivation**: ``output_dir = session_dir``
        and the ``DERIVED_SUBDIRS`` map (``scene_extractions_dir`` and the
        pre-Phase-5 ``roleplay_extract_dir``/``summary_extract_dir`` names
        the session editor renamed to ``*_extractions_dir``). That duplicated
        ``resolve_path``/``_PATH_FIELDS`` — a second, undeclared
        implementation of the same layout convention — and had already
        drifted out of sync with the renamed fields, which is exactly why
        O2 kills the whole derivation half rather than patching the
        two stale names: a function that emits no path *formula* cannot go
        stale when a path field is renamed elsewhere.

        What survives is **discovery**: every field below is either an
        existence probe across multiple candidate names/locations (the
        caller cannot guess which one is real — e.g. ``summaries.md`` vs.
        the legacy ``all_summaries.md``) or a glob (the caller cannot guess
        *what* the matching filenames are, only where to look — e.g.
        ``docs/npcs/*.md``). A field is omitted or ``""`` when nothing is
        found; callers treat that as "nothing to prefill", never as an
        error — see ``deriveAll()``'s ``if (d.<field>) ...`` guards.
        """
        cd = Path(campaign_dir).expanduser().resolve()
        sd = Path(session_dir).expanduser().resolve()
        docs = cd / "docs"
        result: dict[str, str] = {}

        # docs/*.md — presence, not content, decides whether a grounding
        # doc "exists yet" for this campaign.
        for name, key in (
            ("campaign_state.md", "campaign_state"),
            ("world_state.md", "world_state"),
            ("party.md", "party"),
            ("planning.md", "planning"),
        ):
            p = docs / name
            result[key] = str(p) if p.exists() else ""

        # voice/ and examples/ — single-candidate, but the is_dir() check is
        # a genuine probe, not layout arithmetic, and it is load-bearing:
        # deriveAll() runs on a debounced watch of campaign_dir/session_dir,
        # so an unconditional value would silently overwrite a GM's custom
        # voice_dir with a non-existent path every time they switch session.
        # Returning "" when the conventional directory is absent is what
        # makes deriveAll()'s `if (d.voice_dir)` guard preserve their entry.
        for rel, key in (("voice", "voice_dir"), ("examples", "examples_dir")):
            p = cd / rel
            result[key] = str(p) if p.is_dir() else ""

        # summaries.md — the master narrative bible; older campaigns used
        # all_summaries.md, and some keep it under docs/ instead of the
        # campaign root.
        for p in (cd / "summaries.md", cd / "all_summaries.md", docs / "summaries.md"):
            if p.exists():
                result["summaries"] = str(p)
                break

        # party.yaml lives at config/party.yaml — one declared location, no
        # probe (Track 0 of docs/config/grounding-isolation.md). Kept in this
        # discovery result only because SessionConfig.vue's deriveAll() reads
        # it alongside the genuine probes; it is a declared path, so it can
        # move out when that page stops needing it.
        p = config_path(cd, PARTY_CONFIG_FILENAME)
        result["party_config"] = str(p) if p.exists() else ""

        # docs/npcs/*.md — one file per NPC dossier; the set of filenames
        # IS the answer, there is no fixed name to check for.
        npcs_dir = docs / "npcs"
        if npcs_dir.is_dir():
            npc_files = sorted(npcs_dir.glob("*.md"))
            if npc_files:
                result["plan_npc"] = "\n".join(str(f) for f in npc_files)

        # session_dir contents — GM recap and session summary, sniffed by
        # candidate filename (same reasoning as summaries.md/party.yaml
        # above). The raw *.vtt is NOT discovered here: the Session Doc
        # Editor globs for it itself (``scene_editor._vtt_path``), and the
        # page that consumed a discovered ``vtt_input`` is gone.
        for name in ("gm-assist.md", "gm_assist.md", "gmassistant.md", "recap.md"):
            candidate = sd / name
            if candidate.exists():
                result["gm_recap"] = str(candidate)
                break

        for name in ("session-summary.md", "session-clean.md", "session_summary.md"):
            candidate = sd / name
            if candidate.exists():
                result["session_summary"] = str(candidate)
                break

        return result
