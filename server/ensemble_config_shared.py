"""Shared ensemble configuration data models and I/O logic.

Phase 1 of ``docs/config/ensemble-isolation.md``: the grouped, **strict**
(``extra="forbid"``) pydantic models for the ensemble grounding-doc workflow,
plus the YAML load/save pair that owns ``<config>/ensemble.yaml``.

Mirrors ``server/session_editor_config_shared.py`` — module-level load/save
used by both the service layer and (later) the one-shot migration CLI, with
pydantic models rather than dataclasses.

Three things this schema fixes, all documented in the design doc:

* **The default lives here, once.** Every path/tuning literal below is
  currently declared two or three times — in ``config_models.EnsembleSection``,
  in ``server/routers/ensemble.py``'s route signatures, and again as a
  TypeScript fallback in ``frontend/src/views/ensemble/useEnsembleRun.ts``.
  Phase 3 deletes the other copies and reads them from here.
* **``endpoints`` is plural.** ``config_models.BackendProfile`` declares a
  singular ``endpoint``, but the shipped frontend, ``ui_state.yaml``, and both
  ``/run/extract`` and ``/run/bundle`` have used a plural list for some time —
  it survived only because ``EnsembleSection`` is ``extra="allow"``.
  :class:`EnsembleBackend` makes the shipped shape the declared one.
  ``BackendProfile`` itself is deliberately left alone: the Session Doc Editor
  legitimately uses its singular ``endpoint`` for the dgx backend.
* **The six planning overrides are typed.** ``planning_synth_mode``,
  ``planning_npc``, ``planning_arc_scores``, ``planning_context``,
  ``planning_depth`` and ``planning_force_include`` are written by
  ``EnsembleSynthesize.vue`` into a section that has never declared them.
  They become :class:`EnsemblePlanning`.

``campaign_dir`` is deliberately absent — it is platform-tier, owned by
``PlatformConfigService``. The old ``EnsembleSection.campaign_dir`` was a
stale second copy that no run ever read (Phase 0 deleted it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from campaignlib.selection import ModelSelection
from pydantic import BaseModel, ConfigDict, Field

from campaignlib.util import atomic_write_text

ENSEMBLE_CONFIG_FILENAME = "ensemble.yaml"


class EnsembleBackend(ModelSelection):
    """A selectable execution target for one LLM-bearing ensemble stage.

    The API key is NEVER stored here — it is read from the environment
    (ANTHROPIC_API_KEY / OPENROUTER_API_KEY) at run time. ``endpoints`` is a
    list because the extract stage fans out across multiple dgx hosts (see
    ``pipelines/ensemble/ensemble_batch.py``'s two-Spark dispatch); the
    synthesize stage uses at most the first entry.
    """

    model_config = ConfigDict(extra="forbid")

    # Inherits `backend` and `model` from ModelSelection (feature 003); the
    # only field that is genuinely ensemble's own is the PLURAL `endpoints`,
    # because the extract stage fans out across several DGX hosts. That
    # plural/singular split from session_doc.yaml's BackendProfile is
    # load-bearing and deliberately not unified — see
    # specs/003-model-selection-resolution/data-model.md.
    #
    # `backend` is re-declared only to keep the non-optional "anthropic"
    # default this schema has always had. resolve_selection recognises that
    # default as "deferring" when no model is set, so an unconfigured stage
    # still inherits the platform's backend.
    backend: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    endpoints: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """`backend` is non-optional here, so the base class's "backend is
        None" test never fires. For this schema "nothing chosen" means the
        default backend, no model, no endpoints, and no `batch` (feature
        005-ui-batch-selection) — mirroring the fix `ModelSelection.is_empty`
        needed for the same reason (a batch-only override must not be
        classified "empty" and silently dropped). Nothing calls
        `EnsembleBackend.is_empty()` today, but leaving it batch-blind would
        be a latent trap for the first caller that does."""
        return (
            self.backend == "anthropic" and not self.model and not self.endpoints
            and self.batch is None
        )


class EnsemblePaths(BaseModel):
    """Where each stage reads from and writes to.

    Every one of these is currently a literal in a route signature in
    ``server/routers/ensemble.py`` — not settable per campaign without editing
    Python. Declaring them makes a campaign with a different ``docs/`` layout
    configurable instead of forked.
    """

    model_config = ConfigDict(extra="forbid")

    chapters_glob: str = "docs/chapters/chapter_*.md"
    per_chapter_dir: str = "docs/ensemble/per_chapter"
    corpus_glob: str = "docs/ensemble/per_chapter/*/merged.json"
    merged_out: str = "docs/ensemble/merged.json"
    state_dossiers_dir: str = "docs/ensemble/state_dossiers"
    dossiers_glob: str = "docs/ensemble/merged_dossiers/*.md"
    # The npc_-prefixed subset of the same directory. A separate field rather
    # than a derivation of `dossiers_glob`: the two are passed to different
    # things (``dossiers_glob`` is synthesise_world_state's --dossiers value;
    # this one drives planning's NPC auto-detect in the router's helpers), and
    # deriving one from the other would make overriding either surprising.
    npc_dossiers_glob: str = "docs/ensemble/merged_dossiers/npc_*.md"
    threads_out: str = "docs/ensemble/threads.md"
    recent_events_out: str = "docs/recent_events.md"
    # Module inventory passed as --inventory to synthesise_world_state;
    # empty = don't pass.
    inventory: str = ""


class EnsembleTuning(BaseModel):
    """Parallelism and threshold knobs, likewise currently route literals.

    ``bundle_min_facts`` and ``threads_min_facts`` are separate fields on
    purpose: the shipped defaults genuinely differ (3 for ``/run/bundle``,
    2 for ``/run/threads``), and collapsing them into one value would be a
    silent behavior change rather than a refactor.

    **Two window fields, two different tracks.** ``dossier_recent_window``
    scopes ``synthesise_world_state``'s entity-dossier payload (which entities
    count as "now"); ``recent_events_window`` scopes ``build_recent_events``'s
    ``recent_events.md`` (how many chapters of raw events to dump). They answer
    different questions and are deliberately not one knob — changing how much
    event detail you want dumped should not silently change what world_state
    considers current.
    """

    model_config = ConfigDict(extra="forbid")

    chapter_parallel: int = 3
    chunk_parallel: int = 4
    bundle_min_facts: int = 3
    threads_min_facts: int = 2
    # Renamed from `dossier_min_facts` (issue #194): the floor now applies ONLY
    # to entities outside `dossier_recent_window`. Applied to every dossier, as
    # it was, a floor of 10 deleted the newest chapter's entities every run —
    # a debuting entity has the fewest facts by construction.
    background_min_facts: int = 10
    dossier_recent_window: int = 4
    entity_parallel: int = 0
    recent_events_window: int = 0


class EnsemblePlanning(BaseModel):
    """Ensemble-local overrides for planning synthesis.

    These deliberately do NOT collide with the standalone Planning page's own
    npc/arc-score/context lists (``ui.planning``, and ``planning.yaml`` via
    ``PlanningConfigService``) — see ``EnsembleSynthesize.vue``'s comment. The
    shared ``planning_config`` path is not carried here for the same reason:
    it belongs to Planning, and ensemble reads it rather than owning it.
    """

    model_config = ConfigDict(extra="forbid")

    synth_mode: Literal["config", "flat"] = "config"
    npc: list[str] = Field(default_factory=list)
    arc_scores: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    depth: Literal["scene", "full"] = "scene"
    force_include: list[str] = Field(default_factory=list)


class EnsembleConfig(BaseModel):
    """Root model — the ``<config>/ensemble.yaml`` shape.

    Strict (``extra="forbid"``), matching ``SessionEditorConfig`` /
    ``PlanningConfig`` / ``PlatformDocument``. Unlike the ``ui.ensemble``
    section it replaces, an unknown key is an error at write time rather than
    unvalidated overflow that no server code ever reads.
    """

    model_config = ConfigDict(extra="forbid")

    # Principle X — no silent "all": empty means *nothing selected* and
    # extraction refuses to run. "Select all" materializes every path here.
    # Kept at the root rather than under `paths` because it is an operator
    # selection, not a layout declaration.
    chapters_selected: list[str] = Field(default_factory=list)
    extract: EnsembleBackend = Field(default_factory=EnsembleBackend)
    synthesize: EnsembleBackend = Field(default_factory=EnsembleBackend)
    paths: EnsemblePaths = Field(default_factory=EnsemblePaths)
    tuning: EnsembleTuning = Field(default_factory=EnsembleTuning)
    planning: EnsemblePlanning = Field(default_factory=EnsemblePlanning)


def load_ensemble_config(path: Path) -> EnsembleConfig:
    """Load an ``ensemble.yaml`` file.

    A missing file, or one that parses to an empty/null YAML document, returns
    the all-defaults :class:`EnsembleConfig` rather than raising — an
    all-defaults ensemble config is a legitimate state (a campaign that has
    never opened the Setup page), and the "emptied file reads back as 400" bug
    ``docs/config/planning-isolation.md`` had to fix twice is not worth
    re-introducing.

    Malformed YAML still raises ``ValueError``, mirroring
    ``load_session_editor_config`` / ``load_planning_config``.

    Migrate-and-delete shim: ``known_names``/``aliases_path`` were retired in
    favor of the entity registry (``docs/entity_registry.yaml``). A
    pre-migration ``ensemble.yaml`` may still carry them, and the model is
    ``extra="forbid"``, so they are pruned from ``raw`` here, read-only —
    this never rewrites the file; the next ``save_ensemble_config`` (a PUT)
    is what leaves it clean.

    ``tuning.dossier_min_facts`` gets the same treatment with one difference: it
    was **renamed**, not retired (to ``background_min_facts``, issue #194), so
    the shim carries the operator's value across instead of discarding it.
    Dropping it would silently reset a hand-tuned floor back to the default,
    which is exactly the kind of quiet substitution this rename exists to end.
    """
    if not path.exists():
        return EnsembleConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return EnsembleConfig()
    for key in ("known_names", "aliases_path"):
        raw.pop(key, None)
    tuning = raw.get("tuning")
    if isinstance(tuning, dict) and "dossier_min_facts" in tuning:
        old = tuning.pop("dossier_min_facts")
        tuning.setdefault("background_min_facts", old)
    return EnsembleConfig.model_validate(raw)


def save_ensemble_config(path: Path, cfg: EnsembleConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, creating parent dirs as needed.

    Atomic (``campaignlib.util.atomic_write_text``) so a crash mid-write
    leaves the previous config intact rather than a truncated file the next
    load would reject — the same guarantee ``specs/002-ensemble-run-
    observability`` established for the ensemble's own cache artifacts.
    """
    data: dict[str, Any] = cfg.model_dump(mode="json")
    atomic_write_text(
        path,
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
    )
