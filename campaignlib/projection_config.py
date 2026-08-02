"""State-projection configuration — models and YAML I/O for
``<config>/projections.yaml``.

Part of ``docs/config/`` series (see ``docs/config/grounding-isolation.md``
and ``docs/config/planning-isolation.md`` for the pattern this continues).
Lives in ``campaignlib`` rather than ``server`` for the same reason
:mod:`campaignlib.party_config` and :mod:`campaignlib.planning_config` do:
both the CLI engines under ``pipelines/grounding/`` (event spine, thread
registry, section rendering) **and**, later, a ``server/`` service that
exposes them to the UI, need this shape. Putting it in ``server`` would make
the engine import the web app to read its own config — the inversion
``tests/test_layering.py`` exists to forbid, and the exact bug
``pipelines/grounding/party.py``/``planning.py`` had before Phase 1 of
``grounding-isolation.md``.

**Field-for-field, not behavior-for-behavior.** The shape mirrors
:mod:`campaignlib.planning_config`: grouped, strict (``extra="forbid"``)
pydantic models, one root, a ``selection`` field for feature 003. But
``ProjectionConfig``'s fields are all always-present locations with real
defaults — there is no per-entry authored-vs-resolved split here, because
there are no per-entry lists to resolve against a base directory. Every path
is stored, read, and written exactly as authored, relative to the campaign
root; nothing in this module ever calls ``.resolve()`` on one (research D14).
An empty string is never a way to spell "unset" here (data-model.md §1 rule
4) — a field simply omitted from the YAML takes its declared default, which
is why every field below has one.

**Deliberately absent.** No ``corpus`` field: both consumers (event spine,
thread registry) declare ``--corpus`` as a required CLI argument, and a
config default would manufacture an implicit "all chapters" (Constitution X,
research D6, FR-013). No ``sections``/``specs`` field: which sections exist
and which document they belong to stays in Python (FR-014) — a config knob
here would let a "completion" of this schema quietly reintroduce the corpus
default under a different name. ``tests/test_projection_config.py`` asserts
both absences recursively, not by string-matching a snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from campaignlib.selection import ModelSelection
from pydantic import BaseModel, ConfigDict, Field, field_validator

from campaignlib.util import atomic_write_text

PROJECTION_CONFIG_FILENAME = "projections.yaml"


class ProjectionStores(BaseModel):
    """Durable state this service's own CLIs write and read back.

    ``events`` is the single declaration event_spine and grounding_sections
    both resolve from — the freshness hash and every read follow the same
    value, closing the three-site split in research D1 (FR-009). ``tracking``
    is a glob; zero matches is legal and simply skips that section.
    """

    model_config = ConfigDict(extra="forbid")

    events: str = "docs/ensemble/events.jsonl"
    thread_registry: str = "docs/thread_registry.yaml"
    thread_proposals: str = "docs/ensemble/thread_proposals.yaml"
    tracking: str = "docs/tracking*.txt"


class ProjectionInputs(BaseModel):
    """Inputs produced by other services, declared here rather than read
    from their own config documents — a cross-service config read is the
    defect ``_backend_flags`` was deleted for (FR-003, research D5).

    ``dossiers_fallback`` is used when ``dossiers`` yields nothing, and the
    choice is reported rather than silent (FR-024a) — Phandalin has no
    curated ``merged_dossiers/`` set and runs entirely on the fallback today.
    """

    model_config = ConfigDict(extra="forbid")

    dossiers: str = "docs/ensemble/merged_dossiers"
    dossiers_fallback: str = "docs/ensemble/state_dossiers"
    narrative_importance: str = "docs/ensemble/narrative_importance.yaml"
    party: str = "docs/party.md"
    planning_notes: str = "docs/planning_notes.md"
    speculations: str = "notes/thread_speculations.md"


class ProjectionOutput(BaseModel):
    """Where this service writes.

    ``draft`` lives in its own namespace (``docs/projections/``, research
    D13) so the three rendering services never collide; ``legacy_draft`` is
    the pre-move path the FR-007b gate checks before writing, present so the
    gate is declared here rather than hardcoded in the CLI. ``recent_events``
    and ``recent_events_window`` moved from ``ensemble.yaml``'s
    ``paths.recent_events_out`` / ``tuning.recent_events_window`` (research
    D15) — ``build_recent_events`` wraps the event spine, so its output
    belongs to this service, not to ensemble. ``recent_events`` is exempt
    from the own-subdirectory rule ``draft`` follows: it is a promoted-style
    grounding artifact other pipelines already read at this path, not a
    draft awaiting comparison, and it sits outside the legacy gate's scope
    for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    sections_dir: str = "docs/grounding_sections"
    draft: str = "docs/projections/{doc}_draft.md"
    legacy_draft: str = "docs/{doc}_draft.md"
    recent_events: str = "docs/recent_events.md"
    recent_events_window: int = 0

    @field_validator("draft")
    @classmethod
    def _draft_names_the_doc(cls, v: str) -> str:
        """``draft`` is a per-document template, not a fixed path — a value
        without the placeholder would silently collapse every document onto
        one file (data-model.md §1 validation rule 2)."""
        if "{doc}" not in v:
            raise ValueError(
                f"output.draft must contain the literal '{{doc}}' placeholder, got {v!r}"
            )
        return v


class ProjectionConfig(BaseModel):
    """Root model — the ``<config>/projections.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    stores: ProjectionStores = Field(default_factory=ProjectionStores)
    inputs: ProjectionInputs = Field(default_factory=ProjectionInputs)
    output: ProjectionOutput = Field(default_factory=ProjectionOutput)

    #: Feature 003 — this service's own model/backend override. Empty means
    #: "defer to the platform selection", which is the default and the common
    #: case. Set it to run this document's generation on a different model or
    #: backend from the rest of the app, affecting only this service's runs.
    selection: ModelSelection = Field(default_factory=ModelSelection)


def load_projection_config(path: Path) -> ProjectionConfig:
    """Load ``projections.yaml``.

    A missing file, or one that parses to an empty/null YAML document,
    returns the all-defaults config rather than raising — same reasoning as
    :func:`server.grounding_config_shared.load_grounding_config`: an
    all-defaults projection config is a legitimate state (a campaign that has
    never opened this page, or run one of the three CLIs with an explicit
    ``--config``), and the "emptied file reads back as 400" bug
    ``planning-isolation.md`` had to fix twice is not worth re-introducing.
    Malformed YAML raises ``ValueError``; an unknown key or wrong-shaped value
    raises pydantic's ``ValidationError`` via strict (``extra="forbid"``)
    validation.
    """
    if not path.exists():
        return ProjectionConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not raw:
        return ProjectionConfig()
    return ProjectionConfig.model_validate(raw)


def save_projection_config(path: Path, cfg: ProjectionConfig) -> None:
    """Write ``cfg`` to ``path`` atomically, creating parent dirs as needed.

    Every field carries a real default (there is no three-state encoding to
    hand-build, unlike ``party.yaml``/``planning.yaml``'s ``arc_score``), so
    a plain ``model_dump`` is sufficient — mirrors
    :func:`server.grounding_config_shared.save_grounding_config`.
    """
    data: dict[str, Any] = cfg.model_dump(mode="json")
    atomic_write_text(
        path,
        yaml.safe_dump(
            data, default_flow_style=False, sort_keys=False, allow_unicode=True
        ),
    )
