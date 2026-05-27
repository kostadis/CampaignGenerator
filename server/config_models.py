"""Typed pydantic models for CampaignGenerator configuration.

Three documents:
    UIState           — <campaign>/ui_state.yaml         (tracked, server-owned)
    LocalConfig       — <campaign>/.campaigngenerator.local.yaml (gitignored)
    TrackedConfig     — <campaign>/config.yaml           (tracked, human-only)

Path fields stay relative; resolution against campaign_dir happens in the
service layer. Numeric fields rely on pydantic's native string→int coercion
so a stale ``sd_narrate_tokens: '4000'`` from legacy ui_config.yaml can
never shadow an in-code default again.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

SCHEMA_VERSION = 2


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


class SessionDocSection(BaseModel):
    """``ui.session_doc`` — Session Doc Editor (post-session narrative)."""

    model_config = ConfigDict(extra="allow")

    session: OptStr = None
    extract_dir: OptStr = None
    roleplay_dir: OptStr = None
    output_dir: OptStr = None
    summary_dir: OptStr = None
    session_summary: OptStr = None
    scene_extractions_dir: OptStr = None
    narration_dir: OptStr = None
    party: OptStr = None
    voice_dir: OptStr = None
    examples_dir: OptStr = None
    characters: OptStr = None
    gm_player: OptStr = None
    narrate_tokens: int = 16000
    prose_mode: OptBool = False
    reflections: OptBool = False
    narration_genre: OptStr = None
    batch: OptBool = False
    session_name: OptStr = None
    context: list[str] = Field(default_factory=list)
    # LLM backend selector + DGX overrides. Endpoint/model defaults are
    # applied at the route boundary in `scene_editor._llm_env()` so a null
    # value here means "use the runtime default", not "unset".
    backend: Literal["anthropic", "dgx"] = "anthropic"
    dgx_endpoint: OptStr = None
    dgx_model: OptStr = None
    scrub_enabled: OptBool = False
    scrub_tokens: int = 16000


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


class ProfilesSection(BaseModel):
    """``ui.profiles`` — named knob presets for the Session Doc Editor.

    The active profile's knobs are mirrored into ``ui.session_doc`` at the
    moment of activation, so the rest of the system keeps reading from the
    flat overlay unchanged.
    """

    model_config = ConfigDict(extra="allow")

    profiles: list[ProfileEntry] = Field(default_factory=list)
    active: OptStr = None


class UISection(BaseModel):
    """All per-page state, one attribute per page or group of pages."""

    session_doc: SessionDocSection = Field(default_factory=SessionDocSection)
    vtt_summary: VttSummarySection = Field(default_factory=VttSummarySection)
    grounding: GroundingSection = Field(default_factory=GroundingSection)
    profiles: ProfilesSection = Field(default_factory=ProfilesSection)
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


class RuntimeSection(BaseModel):
    """Cross-page runtime state."""

    model_config = ConfigDict(extra="allow")

    default_model: str = "claude-sonnet-4-6"
    session_dir: OptStr = None


class LegacySection(BaseModel):
    """Quarantine for keys the migrator could not place into a typed slot."""

    model_config = ConfigDict(extra="allow")

    unmigrated: dict[str, Any] = Field(default_factory=dict)


class UIState(BaseModel):
    """Root model for ``<campaign>/ui_state.yaml``."""

    model_config = ConfigDict(extra="allow")

    version: int = SCHEMA_VERSION
    ui: UISection = Field(default_factory=UISection)
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)
    legacy: LegacySection = Field(default_factory=LegacySection)


class ServerSection(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5000


class NavSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    last_page: OptStr = None


class LocalConfig(BaseModel):
    """Root model for ``<campaign>/.campaigngenerator.local.yaml``."""

    model_config = ConfigDict(extra="allow")

    server: ServerSection = Field(default_factory=ServerSection)
    nav: NavSection = Field(default_factory=NavSection)


# ── Public list of typed UI section names ──────────────────────────────────
# The service uses this to validate ``PUT /api/config/section/{name}``.

UI_SECTION_NAMES: tuple[str, ...] = tuple(UISection.model_fields.keys())
