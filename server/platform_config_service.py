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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import HTTPException, Request
from pydantic import ValidationError

from campaignlib import DEFAULT_MODEL, wiring_get
from campaignlib.constants import config_path
from campaignlib.party_config import PARTY_CONFIG_FILENAME
from server.platform_config_shared import (
    LOCAL_CONFIG_NAME,
    PLATFORM_CONFIG_NAME,
    ConfigError,
    ModelSelection,
    PlatformConfig,
    PlatformDocument,
    PlatformLocalConfig,
    PlatformRuntime,
    compatible,
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


# ── The resolution seam (feature 003) ─────────────────────────────────────


class IncompatibleSelection(HTTPException):
    """Raised when the resolved model cannot be served by the resolved
    backend — the run is refused before any subprocess is spawned.

    409 rather than 400 because the *request* is well formed; it is the
    stored state that conflicts. The ``service`` and ``remedy`` fields are
    what let the UI offer "Clear override" at the point of refusal instead of
    sending the operator hunting for which service holds the stale value.

    **Subclassing HTTPException is deliberate.** This began as a bare
    ``Exception`` with a handler registered in ``server/main.py``, which meant
    the 409 only existed for apps built by that module — any app that included
    a router directly (as several test fixtures do) got an unhandled 500
    instead. A refusal that degrades to a crash depending on how the app was
    assembled is worse than no refusal at all, because it looks like a bug in
    the run rather than a decision about the selection. As an HTTPException
    subclass it renders through FastAPI's built-in handler wherever the router
    is mounted, with no registration to forget.
    """

    def __init__(self, resolved: "ResolvedSelection", service: str | None = None) -> None:
        self.resolved = resolved
        self.service = service
        super().__init__(status_code=409, detail=self._detail(resolved, service))

    @staticmethod
    def _detail(r: "ResolvedSelection", service: str | None) -> dict[str, Any]:
        return {
            "error": "incompatible_selection",
            "message": r.refusal,
            "model": r.model,
            "model_origin": r.model_origin,
            "backend": r.backend,
            "backend_origin": r.backend_origin,
            "service": service,
            "remedy": "clear_override" if r.model_origin == "service" else "change_platform",
        }

    def as_detail(self) -> dict[str, Any]:
        return self._detail(self.resolved, self.service)


@dataclass(frozen=True)
class ResolvedSelection:
    """What a single run will actually use, and where each half came from.

    Computed per request and discarded — it is deliberately NOT persisted.
    The durable record of what a run used is the run log written by
    ``server/subprocess_runner.py::_save_run_log``, whose ``command`` line
    already carries the ``--model``/``--backend``/``--batch`` flags built
    from this.

    ``batch``/``batch_origin`` (feature 005-ui-batch-selection) mirror
    ``model``/``backend`` in shape, but are resolved independently — see
    ``resolve_selection``'s batch block. An unsatisfiable batch selection
    (a non-anthropic backend, or a service whose batch capability is
    ``incompatible``) populates the same ``refusal`` field model/backend
    incompatibility already uses, naming batch as the cause, rather than
    growing a second refusal field (research D2).
    """

    model: str
    backend: str
    model_origin: str  # request | service | platform | literal
    backend_origin: str  # request | service | platform
    endpoint: str | None = None
    endpoints: tuple[str, ...] = ()
    refusal: str | None = None
    batch: bool = False
    batch_origin: str = "platform"  # request | service | platform

    @property
    def compatible(self) -> bool:
        return self.refusal is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "backend": self.backend,
            "model_origin": self.model_origin,
            "backend_origin": self.backend_origin,
            "batch": self.batch,
            "batch_origin": self.batch_origin,
            "compatible": self.compatible,
            "refusal": self.refusal,
        }


# ── Batch capability map (feature 005-ui-batch-selection, research D7) ─────
# Static and per-service, keyed on the same `service_name` strings already
# passed to resolve_selection() at each call site. Cannot be derived at
# runtime without the server reasoning about batch (Constitution VI), so this
# is a plain, reviewable table sourced from the CLIs' actual behavior as
# merged in spec 004-claude-api-batch — see docs/cli/cli_tools.md's
# "Shared flag: --batch" section and specs/005-ui-batch-selection/data-model.md.
#
#   full        — independent calls grouped into one submission.
#   degraded    — an ordered chain that runs as sequential one-item batches:
#                 same discount, slower, never refused (FR-010 states the
#                 trade-off in the UI, not here).
#   incompatible — the tool cannot act on batch at all; only this state
#                 changes resolve_selection's refusal (below). No UI-reachable
#                 service occupies it today (the one CLI that does — the
#                 optional polish pass — is not wired into the UI, so it never
#                 reaches this map by service_name; specified anyway so wiring
#                 it in later inherits the rule).
#   excluded    — out of scope for batch entirely (the Connection Graph,
#                 FR-013/FR-014): its preview must not grow a batch field at
#                 all, which is enforced where that preview is built
#                 (server/routers/connections.py), not by this map — a
#                 service_name absent from resolve_selection's refusal check
#                 simply never refuses on batch's account.
#
# A service_name with no entry here (including None, since several run routes
# do not pass one at all) defaults to "full" — the permissive, pre-existing
# behavior — rather than silently refusing a run this map has no opinion on.
BatchCapability = Literal["full", "degraded", "incompatible", "excluded"]

BATCH_CAPABILITY: dict[str, BatchCapability] = {
    # Grounding's own sub-documents (server/routers/grounding.py) — each is
    # one or more independent calls grouped into a single submission.
    "campaign_state": "full",
    "distill": "full",
    # Shared by grounding.py's /run/party + /run/planning (build-dossiers)
    # AND the standalone Party/Planning services (party_routes.py /
    # planning_routes.py) — same underlying CLI (party.py / planning.py)
    # either way, so one entry covers both.
    "party": "full",
    "planning": "full",
    "ensemble": "full",
    # session-prep's 5 stages are an ordered chain — sequential one-item
    # batches (docs/cli/cli_tools.md). Only the /selection/resolved preview
    # passes this service_name today; /run/npc-table and /run/query (also in
    # prep.py) pass none, so they fall to the "full" default above, which
    # matches their own actual (single-call) capability.
    "prep": "degraded",
    "setup": "full",
    # Session Doc Editor (server/routers/scene_editor.py): every stage shares
    # this one service_name today. Most (scene_extract, enhance_summary,
    # sd_plan, sd_consistency) are full; sd_narrate's handoff-threaded scenes
    # are degraded. Classified degraded as the conservative choice until the
    # router distinguishes stages — see the "Risk noted" paragraph of D7.
    "session_doc": "degraded",
    "connections": "excluded",
    # State Projection (server/routers/projections.py, 006-state-projection-
    # service): `grounding_sections build` has no `--batch` flag at all
    # (contracts/cli.md) — this is the first service_name to actually land
    # in the "incompatible" state the map's own comment anticipated. Without
    # this entry a platform-wide batch default would reach `/run/build` and
    # `selection_cli_args` would append `--batch` to a subprocess whose
    # argparse doesn't know the flag, failing opaquely instead of with the
    # same clear 409 every other incompatible selection gets.
    "projections": "incompatible",
}


def _batch_capability(service_name: str | None) -> BatchCapability:
    if not service_name:
        return "full"
    return BATCH_CAPABILITY.get(service_name, "full")


def resolve_selection(
    request: Request,
    *,
    request_model: str | None = None,
    request_backend: str | None = None,
    request_batch: bool | None = None,
    service: ModelSelection | Any | None = None,
    service_name: str | None = None,
    raise_on_incompatible: bool = True,
) -> ResolvedSelection:
    """The single place model/backend resolution happens.

    ``model   := request ?? service ?? platform.default_model  ?? DEFAULT_MODEL``
    ``backend := request ?? service ?? platform.default_backend``

    **The pairing rule.** Model and backend are taken from the *same tier*
    whenever that tier supplies either. A service that sets only ``model``
    inherits the platform's backend, and the resulting pair is then checked
    by ``compatible()``. Resolving the two fields independently is exactly
    what produced the pre-003 defect: ``grounding.py`` took its model from
    the platform and its backend from the Session Doc Editor's config, so a
    run could carry a Claude id and a DGX backend and still "work" — because
    the DGX adapter silently substituted its own default.

    **No substitution.** When the resolved pair is incompatible this raises
    (or, with ``raise_on_incompatible=False``, returns a selection carrying
    a ``refusal``). It never quietly swaps in a model the operator did not
    choose. That reverses the behaviour ``ensemble.py::_backend_args`` used
    to have, deliberately — see the spec's Clarifications.

    ``service`` accepts any object with ``backend``/``model`` attributes, so
    the two pre-existing shapes (``EnsembleBackend`` with plural
    ``endpoints``, ``BackendProfile`` with singular ``endpoint``) pass
    through unchanged and keep their endpoint fields.

    **Batch** (feature 005-ui-batch-selection) resolves in this same function
    with the same request -> service -> platform precedence, via
    ``request_batch`` and ``getattr(service, "batch", None)`` /
    ``runtime.default_batch``. It is NOT subject to the pairing rule above —
    see the batch block below. A batch selection that cannot be honoured (a
    non-anthropic backend, or a service whose static batch capability is
    ``incompatible`` — see ``BATCH_CAPABILITY``) populates this same
    ``refusal``/``raise_on_incompatible`` machinery, naming batch as the
    cause; there is no separate downgrade path (FR-006).
    """
    try:
        platform = require_platform(request)
        runtime = platform.runtime
    except (HTTPException, AttributeError):
        # No live platform. Two ways to get here, both tolerated rather than
        # turned into a 503: a request handled outside the normal boot
        # lifecycle (HTTPException, mirroring resolve_default_model), and a
        # caller that has no Request at all (AttributeError) — command
        # builders are unit-tested directly, and refusing to resolve without
        # a live server would make them untestable in isolation.
        runtime = None

    plat_model = (getattr(runtime, "default_model", None) or DEFAULT_MODEL) if runtime else DEFAULT_MODEL
    plat_backend = (getattr(runtime, "default_backend", None) or "anthropic") if runtime else "anthropic"

    svc_model = (getattr(service, "model", None) or "").strip() or None if service is not None else None
    svc_backend = (getattr(service, "backend", None) or "").strip() or None if service is not None else None

    # A service whose backend is the schema default ("anthropic") while its
    # model is unset is indistinguishable from "unset" — treat it as deferring.
    if service is not None and svc_model is None and svc_backend == "anthropic":
        svc_backend = None

    if request_backend:
        backend, backend_origin = request_backend, "request"
    elif svc_backend:
        backend, backend_origin = svc_backend, "service"
    else:
        backend, backend_origin = plat_backend, "platform"

    if request_model:
        model, model_origin = request_model, "request"
    elif svc_model:
        model, model_origin = svc_model, "service"
    elif backend_origin != "platform" and backend != plat_backend:
        # THE PAIRING RULE, the half that is easy to get wrong.
        #
        # The tier that chose the backend did not choose a model, and the
        # platform's model belongs to the *platform's* backend — a Claude id
        # picked for the Anthropic API is meaningless on a DGX box. Inheriting
        # it across a backend boundary would manufacture an incompatible pair
        # out of two individually valid choices, and then refuse a run the
        # operator configured correctly.
        #
        # So: no model. The downstream script applies its own default (dgxlib's
        # registry for dgx, OpenRouter's for openrouter), which is what
        # happened before 003 and is a *tool* default rather than a
        # substitution of anybody's pick.
        model, model_origin = "", backend_origin
    elif plat_model:
        model, model_origin = plat_model, "platform"
    else:
        model, model_origin = DEFAULT_MODEL, "literal"

    endpoint = getattr(service, "endpoint", None) if service is not None else None
    endpoints = tuple(getattr(service, "endpoints", ()) or ()) if service is not None else ()

    # A dgx run needs an endpoint, and the platform tier has no field for one
    # — wiring.yaml is already the platform's source for external endpoints
    # and data roots (docs/config/service-cut.md), so an inheriting service
    # resolves it from there. Before 003 this reached grounding.py only by way
    # of the Session Doc Editor's dgx profile, which is the cross-service read
    # FR-005 removes.
    #
    # Note the *model* deliberately does NOT fall back to wiring's dgx_model:
    # that would be a substitution of the operator's pick (FR-011). If the
    # platform backend is dgx while its model is a claude-* id, the pair is
    # incompatible and the run is refused — the operator picks a dgx model.
    if backend == "dgx" and not endpoint and not endpoints:
        endpoint = wiring_get("dgx_endpoint")

    # ── Batch (feature 005-ui-batch-selection) ──────────────────────────
    # Same request -> service -> platform precedence as backend, above, but
    # resolved independently of it: the pairing rule is a model/backend-only
    # rule (research D2) — a service that overrides just `batch` must not
    # thereby be treated as though it also chose this tier's model or
    # backend. `svc_batch is None` means "this service defers"; `False` is a
    # genuine, sticky choice that does not follow an app-wide change
    # (data-model.md's "Batch selection, by tier" table).
    plat_batch = bool(getattr(runtime, "default_batch", False)) if runtime else False
    svc_batch = getattr(service, "batch", None) if service is not None else None

    if request_batch is not None:
        batch, batch_origin = bool(request_batch), "request"
    elif svc_batch is not None:
        batch, batch_origin = bool(svc_batch), "service"
    else:
        batch, batch_origin = plat_batch, "platform"

    refusal = None
    if not compatible(model, backend):
        refusal = f'"{model}" is not a valid model for the {backend} backend.'
    elif batch and backend != "anthropic":
        # Batch is a cost-savings measure, not a preference (research D2): an
        # unsatisfiable batch selection is an incompatible selection in
        # exactly the sense the model/backend check above already models,
        # not something to quietly drop. Origin-independent (D3) — an
        # inherited app-wide batch refuses exactly as a per-service one does,
        # since neither `batch` nor `batch_origin` participates in this
        # check.
        refusal = (
            f'batch is a Claude API option; this run resolves to the '
            f'"{backend}" backend.'
        )
    elif batch and _batch_capability(service_name) == "incompatible":
        refusal = (
            f'batch is a Claude API option; "{service_name}" has no batch '
            f'capability.'
        )

    resolved = ResolvedSelection(
        model=model,
        backend=backend,
        model_origin=model_origin,
        backend_origin=backend_origin,
        endpoint=endpoint,
        endpoints=endpoints,
        refusal=refusal,
        batch=batch,
        batch_origin=batch_origin,
    )
    if refusal and raise_on_incompatible:
        raise IncompatibleSelection(resolved, service_name)
    return resolved


def selection_cli_args(resolved: ResolvedSelection) -> list[str]:
    """Build the ``--model``/``--backend``/``--endpoint(s)``/``--batch``
    flags for a run — the ONLY place any of them is built (Constitution V;
    ``tests/test_backend_seam_guardrails.py`` greps ``server/routers/`` for a
    stray ``"--batch"`` literal to enforce it for the last of the four).

    Exactly ONE ``--model`` is emitted, always. The pre-003 Grounding path
    emitted two (one from the platform, one from ``backend_cli_args``) and
    relied on argparse last-wins; that is contract guarantee C1's target.

    ``backend_cli_args`` is reused for the backend half so the flag
    vocabulary stays defined in one place — it is correctly scoped to
    *formatting* and only the *resolving* half was broken.

    ``--batch`` (feature 005-ui-batch-selection) is appended last, and only
    when ``resolved.batch`` is true. A resolved selection that reaches this
    function has already passed ``resolve_selection``'s compatibility check,
    so ``--batch`` is never emitted alongside a non-anthropic ``--backend``
    — the UI and the command line cannot disagree about the same run.
    """
    from server.backend_forwarding import backend_cli_args

    args = backend_cli_args(
        resolved.backend,
        endpoint=resolved.endpoint,
        endpoints=list(resolved.endpoints),
    )
    # An empty model means "the tier that chose the backend chose no model" —
    # see the pairing rule in resolve_selection. Emitting no --model lets the
    # downstream script apply its own default, which is a tool default rather
    # than a substitution of the operator's pick.
    args += ["--model", resolved.model] if resolved.model else []
    if resolved.batch:
        args.append("--batch")
    return args


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
