"""Shared grounding-doc configuration models and I/O for ``<config>/grounding.yaml``.

Phase 6 of ``docs/config/grounding-isolation.md``. Mirrors
``server/ensemble_config_shared.py``: grouped, **strict** (``extra="forbid"``)
pydantic models plus the YAML load/save pair, used by both the service layer
and the one-shot migration CLI.

**Why one document for four pages.** ``campaign_state``, ``distill``, ``party``
and ``planning`` are not four services — they are one pipeline (extract → human
review → synthesize) run four times over four inputs, through one router
(``server/routers/grounding.py``), with a near-identical parameter block each
time. Four services would mean four schemas and four migration CLIs
maintaining the same shape. One document, one service, one shared base model.

Four things this schema fixes, all code-verified in the design doc:

* **``ui.campaign_state`` and ``ui.distill`` were write-never.** Both Vue pages
  read six keys on mount; neither ever called ``updateSection``. Every value
  the GM typed was lost on reload, recoverable only by hand-editing
  ``ui_state.yaml``.
* **``ui.party`` and ``ui.planning`` persisted 2 of 9 and 2 of 12 fields.** The
  rest were dead reads against keys nothing wrote — what an unmodelled
  ``extra="allow"`` section buys you.
* **The routes read no config at all.** Every default is a literal in a route
  signature (``chunk_size: int = 60000``, five times), with a *different*
  default for ``split_chapters`` in Python (``""``) than in all four Vue pages
  (``'# Chapter'``). Phase 8 points the routes here.
* **``summaries`` was filed as a service.** ``ui.grounding`` holds one
  campaign-wide input pointer that all four runs consume. It moves to this
  document's root, where an empty per-doc ``input`` inherits it — the
  precedence the Vue pages currently hand-code as
  ``r.input || g.summaries || v.summaries``.

Paths are stored **relative to the campaign root** and are not resolved here —
the CLI engines run with ``cwd == campaign_dir``, and this matches the base
Phase 2 established for ``party.yaml``/``planning.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from campaignlib.util import atomic_write_text
from server.config_models import OptStr

GROUNDING_CONFIG_FILENAME = "grounding.yaml"

#: Shipped default for the chunk-splitting heading prefix. The Python routes
#: defaulted to "" while all four Vue pages defaulted to '# Chapter'; the Vue
#: value is the one that has actually been in use, so it is the declared one.
DEFAULT_SPLIT_CHAPTERS = "# Chapter"

#: Shipped default chunk size, previously a literal in five route signatures.
DEFAULT_CHUNK_SIZE = 60000


class GroundingRun(BaseModel):
    """Knobs shared by all four grounding-doc runs.

    ``input`` empty means *inherit the root ``summaries`` pointer* — it is not
    a silent "no input". A run with neither an explicit ``input`` nor a root
    ``summaries`` has nothing to extract from and the route refuses it, per the
    "no silent all" precedent ``ensemble.yaml``'s ``chapters_selected`` set.
    """

    model_config = ConfigDict(extra="forbid")

    input: OptStr = None
    output: OptStr = None
    extract_dir: OptStr = None
    split_chapters: str = DEFAULT_SPLIT_CHAPTERS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    context: list[str] = Field(default_factory=list)
    no_log: bool = False


class CampaignStateRun(GroundingRun):
    """campaign_state.md — completed vs currently-true state.

    ``track_files`` + ``track_items`` replace three separate UI fields:
    ``track_file`` (singular), ``track_files_extra`` (a newline textarea) and
    ``track`` (inline items). The CLI has always taken ``--track-file`` as
    ``action="append"`` (``campaign_state.py:158``), so the singular/plural
    split existed only in the UI.
    """

    track_files: list[str] = Field(default_factory=list)
    track_items: list[str] = Field(default_factory=list)


class DistillRun(GroundingRun):
    """world_state.md — living canon by NPC / faction / location / thread."""


class PartyRun(GroundingRun):
    """party.md. ``mode='config'`` reads the roster from ``party.yaml``
    (``PartyConfigService``); ``'flat'`` is the legacy per-file-list form.

    ``config_path`` points at the roster document rather than embedding it:
    ``party.yaml`` is hand-authored campaign content with a CLI consumer and
    git-meaningful diffs, while everything else here is machine-written state
    that churns on every UI edit (D1).
    """

    mode: Literal["config", "flat"] = "config"
    config_path: OptStr = None
    characters: list[str] = Field(default_factory=list)
    backstory: list[str] = Field(default_factory=list)
    arc_scores: list[str] = Field(default_factory=list)


class DossierBuild(BaseModel):
    """planning --build-dossiers: the per-NPC dossier seeding sub-run.

    A nested group rather than ``build_``-prefixed siblings, because it is a
    genuinely separate invocation of the CLI with its own inputs — the flat
    prefix was how it rode along on an unmodelled section.
    """

    model_config = ConfigDict(extra="forbid")

    summaries: OptStr = None
    dossier_dir: str = "docs/npcs/"
    extract_dir: OptStr = None
    split_chapters: str = DEFAULT_SPLIT_CHAPTERS
    since: int = 0


class PlanningRun(GroundingRun):
    """planning.md — forward-looking NPC/faction dossiers.

    ``synth_mode`` rather than ``mode``: the page's ``mode`` toggle chooses
    between *synthesize* and *build-dossiers*, which is a choice of which
    command to run, not a config value. Only the input-shape choice is stored.
    """

    synth_mode: Literal["config", "flat"] = "config"
    config_path: OptStr = None
    npc: list[str] = Field(default_factory=list)
    arc_scores: list[str] = Field(default_factory=list)
    dossiers: DossierBuild = Field(default_factory=DossierBuild)


class GroundingConfig(BaseModel):
    """Root model — the ``<config>/grounding.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    #: The canonical timeline every grounding run reads by default. Lives at
    #: the root because all four consume it (D2); a per-doc ``input`` overrides
    #: it. SessionConfig.vue writes it here instead of ``ui.grounding``.
    summaries: OptStr = None

    campaign_state: CampaignStateRun = Field(default_factory=CampaignStateRun)
    distill: DistillRun = Field(default_factory=DistillRun)
    party: PartyRun = Field(default_factory=PartyRun)
    planning: PlanningRun = Field(default_factory=PlanningRun)

    def input_for(self, doc: str) -> str | None:
        """The effective input for ``doc``: its own ``input``, else the shared
        ``summaries``. Returns None when neither is set — the caller refuses to
        run rather than guessing (no silent "all").
        """
        run = getattr(self, doc, None)
        if run is None:
            raise KeyError(f"unknown grounding doc {doc!r}")
        return (run.input or "").strip() or (self.summaries or "").strip() or None


#: The four promotable grounding docs, in the order the UI presents them.
GROUNDING_DOCS: tuple[str, ...] = ("campaign_state", "distill", "party", "planning")


def load_grounding_config(path: Path) -> GroundingConfig:
    """Load ``grounding.yaml``.

    A missing file, or one parsing to an empty/null document, returns the
    all-defaults config rather than raising — an all-defaults grounding config
    is a legitimate state (a campaign that has never opened these pages), and
    the "emptied file reads back as 400" bug ``planning-isolation.md`` fixed
    twice is not worth re-introducing. Malformed YAML raises ``ValueError``.
    """
    if not path.exists():
        return GroundingConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return GroundingConfig()
    return GroundingConfig.model_validate(raw)


def save_grounding_config(path: Path, cfg: GroundingConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, creating parent dirs as needed."""
    data: dict[str, Any] = cfg.model_dump(mode="json")
    atomic_write_text(
        path,
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
    )
