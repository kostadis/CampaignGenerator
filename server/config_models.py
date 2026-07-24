"""Typed pydantic models for CampaignGenerator configuration.

    UIState           — <campaign>/ui_state.yaml         (tracked, server-owned)
    TrackedConfig     — <campaign>/config.yaml           (tracked, human-only)

The third document, ``<campaign>/.campaigngenerator.local.yaml``, used to be
modelled here too (``LocalConfig``/``ServerSection``/``NavSection``). Per
``docs/config/platform-isolation.md`` Phase 2 it moved to
``server/platform_config_shared.py`` (``PlatformLocalConfig``/
``PlatformServer``/``PlatformNav``, now strict) alongside the
``PlatformConfigService`` that exclusively owns it — that file has never
overlapped with ``ui_state.yaml``, so there was no reason to keep modelling
it next to ``UIState``.

Phase 3 of the same doc (O3) does the same thing to ``runtime``:
``RuntimeSection`` (``default_model``, ``session_dir``) is retired from this
module entirely and its data relocates to a dedicated ``<config>/
platform.yaml`` that ``PlatformConfigService`` owns outright — see
``server/platform_config_shared.py``'s ``PlatformRuntime``/
``PlatformDocument`` and ``server/migrate_platform_config.py`` for the
one-shot data lift. ``UIState`` stays ``extra="allow"``, so a pre-migration
file's leftover top-level ``runtime:`` block loads harmlessly and is simply
ignored — the same precedent Phase 5 of the session-editor isolation set for
a stale ``ui.session_doc``/``ui.profiles`` block.

Path fields stay relative; resolution against campaign_dir happens in the
service layer. Numeric fields rely on pydantic's native string→int coercion
so a stale ``sd_narrate_tokens: '4000'`` from legacy ui_config.yaml can
never shadow an in-code default again.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# Bumped 2 -> 3 for Phase 3 of docs/config/platform-isolation.md (O3): this
# is the second structural removal from UIState (after Phase 5's
# session_doc/profiles), which is why the field carries information again —
# Phase 5 left it at 2 while removing two sections.
SCHEMA_VERSION = 3


def _empty_to_none(v: Any) -> Any:
    """Treat empty/whitespace strings as 'unset' so type defaults take over."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _none_to_false(v: Any) -> Any:
    """Coerce a YAML/JSON ``null`` to ``False`` so legacy/UI writes that
    leave a bool field unset never break schema validation."""
    return False if v is None else v


OptStr = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptBool = Annotated[bool, BeforeValidator(_none_to_false)]


class _LooseSection(BaseModel):
    """Typed section with no enforced shape — for pages we haven't fully modelled.

    Migration still routes a legacy prefix (``cs_*``, ``plan_*``, etc.) into
    one of these so nothing lands in ``legacy.unmigrated`` just because the
    field hasn't been enumerated. Pages keep working unchanged.
    """

    model_config = ConfigDict(extra="allow")


class VttSummarySection(BaseModel):
    """``ui.vtt_summary`` — VTT Summary page."""

    model_config = ConfigDict(extra="allow")

    input: OptStr = None
    output: OptStr = None
    context: list[str] = Field(default_factory=list)
    date: OptStr = None
    session_name: OptStr = None
    extract_dir: OptStr = None
    reference_summaries: OptStr = None
    # Set by the workflow router after a successful run so future page loads
    # see the produced path without a manual save (fixes VttSummary.vue:70-71).
    session_summary: OptStr = None


class GroundingSection(BaseModel):
    """``ui.grounding`` — top-level pointer to the concatenated summaries file."""

    model_config = ConfigDict(extra="allow")

    summaries: OptStr = None


class ProfileEntry(BaseModel):
    """A named preset of Stage-④ Narrate knobs.

    Paths are NOT part of a profile — they are per-session. Only the knobs
    that change between runs (token budget, prose mode, reflections, the
    enhanced-sections toggle, the genre directive, the backend choice) are
    captured.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    knobs: dict[str, Any] = Field(default_factory=dict)


class BackendProfile(BaseModel):
    """A selectable execution target for one LLM-bearing ensemble stage.

    The API key is NEVER stored here — it is read from the environment
    (ANTHROPIC_API_KEY / OPENROUTER_API_KEY) at run time. `endpoint` is used
    for the dgx backend; openrouter uses its own base URL; claude-code bills
    the Pro/Max subscription via the local `claude` CLI instead of a key.
    """

    model_config = ConfigDict(extra="allow")

    backend: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    endpoint: OptStr = None
    model: OptStr = None


class EnsembleSection(BaseModel):
    """``ui.ensemble`` — the ensemble grounding-doc workflow page.

    Per-stage backend choice (extract vs synthesize are independent) plus the
    scope inputs (known-names sources, aliases file) the bundle stage and the
    alias-correction gate consume. Files on disk remain the source of truth;
    this only records the operator's selections.

    **Being retired.** ``docs/config/ensemble-isolation.md`` replaces this
    section with a strict ``EnsembleConfig`` in its own ``<config>/
    ensemble.yaml`` (``server/ensemble_config_shared.py``). Phase 5 of that
    doc removes ``ensemble`` from :class:`UISection` entirely; until the
    migration CLI ships, this stays so a pre-migration campaign keeps loading.

    Phase 0 deleted the ``campaign_dir`` field: the frontend persisted it and
    read it back, but no ensemble run has ever consumed it, and the platform
    tier (``PlatformConfigService``) is its real owner. A leftover
    ``campaign_dir`` in an existing ``ui_state.yaml`` is harmless — this model
    is ``extra="allow"``, so it loads and is ignored.
    """

    model_config = ConfigDict(extra="allow")

    chapters_glob: str = "docs/chapters/chapter_*.md"
    # The explicit set of chapters chosen in the picker (relative paths).
    # Principle X — there is no silent "all": empty means *nothing selected*
    # and extraction refuses to run; "Select all" materializes every path here.
    chapters_selected: list[str] = Field(default_factory=list)
    extract: BackendProfile = Field(default_factory=BackendProfile)
    synthesize: BackendProfile = Field(default_factory=BackendProfile)
    known_names: list[str] = Field(default_factory=list)
    aliases_path: OptStr = None


class UISection(BaseModel):
    """All per-page state, one attribute per page or group of pages."""

    vtt_summary: VttSummarySection = Field(default_factory=VttSummarySection)
    grounding: GroundingSection = Field(default_factory=GroundingSection)
    ensemble: EnsembleSection = Field(default_factory=EnsembleSection)
    campaign_state: _LooseSection = Field(default_factory=_LooseSection)
    distill: _LooseSection = Field(default_factory=_LooseSection)
    party: _LooseSection = Field(default_factory=_LooseSection)
    planning: _LooseSection = Field(default_factory=_LooseSection)
    prep: _LooseSection = Field(default_factory=_LooseSection)
    npc: _LooseSection = Field(default_factory=_LooseSection)
    query: _LooseSection = Field(default_factory=_LooseSection)
    workflow: _LooseSection = Field(default_factory=_LooseSection)
    connections: _LooseSection = Field(default_factory=_LooseSection)
    experimental: _LooseSection = Field(default_factory=_LooseSection)


class LegacySection(BaseModel):
    """Quarantine for keys the migrator could not place into a typed slot."""

    model_config = ConfigDict(extra="allow")

    unmigrated: dict[str, Any] = Field(default_factory=dict)


class UIState(BaseModel):
    """Root model for ``<campaign>/ui_state.yaml``."""

    model_config = ConfigDict(extra="allow")

    version: int = SCHEMA_VERSION
    ui: UISection = Field(default_factory=UISection)
    legacy: LegacySection = Field(default_factory=LegacySection)


# ── Public list of typed UI section names ──────────────────────────────────
# The service uses this to validate ``PUT /api/config/section/{name}``.

UI_SECTION_NAMES: tuple[str, ...] = tuple(UISection.model_fields.keys())
