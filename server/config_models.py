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

# Bumped 3 -> 4 for Phase 5 of docs/config/ensemble-isolation.md: the third
# structural removal from UIState, after Phase 5 of session-editor isolation
# (session_doc/profiles) and Phase 3 of platform isolation (runtime). As with
# those, UIState stays extra="allow", so a pre-migration file's leftover
# ui.ensemble block loads harmlessly and is ignored — migrate it with
# `python -m server.migrate_ensemble_config` before relying on it.
SCHEMA_VERSION = 4


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


class UISection(BaseModel):
    """All per-page state, one attribute per page or group of pages."""

    grounding: GroundingSection = Field(default_factory=GroundingSection)
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
