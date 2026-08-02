# Data Model: State-Projection Rendering as its own service

**Feature**: 006-state-projection-service | **Date**: 2026-08-01

Two layers: the **configuration document** this feature introduces, and the **durable entities** it
points at (which already exist on disk and are unchanged in shape — only how they are located
changes). Field-level facts about the existing entities come from `research.md` D1/D3/D4.

## 1. `ProjectionConfig` — `<config>/projections.yaml`

Strict (`extra="forbid"`), pydantic, modelled in `campaignlib/projection_config.py`. Missing or empty
file → all-defaults. Malformed YAML → `ValueError`. Atomic save via
`campaignlib.util.atomic_write_text`. All paths are **relative to the campaign root** and are used as
stored (research D14).

```yaml
stores:
  events: docs/ensemble/events.jsonl
  thread_registry: docs/thread_registry.yaml
  thread_proposals: docs/ensemble/thread_proposals.yaml
  tracking: docs/tracking*.txt

inputs:
  dossiers: docs/ensemble/merged_dossiers
  dossiers_fallback: docs/ensemble/state_dossiers
  narrative_importance: docs/ensemble/narrative_importance.yaml
  party: docs/party.md
  planning_notes: docs/planning_notes.md
  speculations: notes/thread_speculations.md

output:
  sections_dir: docs/grounding_sections
  draft: docs/projections/{doc}_draft.md
  legacy_draft: docs/{doc}_draft.md
  recent_events: docs/recent_events.md
  recent_events_window: 0

selection: {}
```

### `ProjectionStores` — written by this service's own CLIs

| Field | Type | Default | Rules |
|---|---|---|---|
| `events` | str | `docs/ensemble/events.jsonl` | Single declaration; the freshness hash **and** every read resolve from it (FR-009). Closes the three-site split in research D1. |
| `thread_registry` | str | `docs/thread_registry.yaml` | GM-ratified canon; every write runs the registry's own `check` |
| `thread_proposals` | str | `docs/ensemble/thread_proposals.yaml` | Holding area; rulings survive re-proposal (FR-021) |
| `tracking` | str | `docs/tracking*.txt` | A glob. Zero matches is legal — the tracking section skips |

**No `corpus` field.** Deliberate and test-asserted (research D6, FR-013): both consumers declare
`--corpus` as `required=True`, and a default would manufacture an implicit "all chapters".

### `ProjectionInputs` — produced by other services, declared here

| Field | Type | Default | Rules |
|---|---|---|---|
| `dossiers` | str | `docs/ensemble/merged_dossiers` | Curated set; preferred |
| `dossiers_fallback` | str | `docs/ensemble/state_dossiers` | Used when `dossiers` yields nothing; **the choice is reported** (FR-024a). Live case: Phandalin has no curated set |
| `narrative_importance` | str | `docs/ensemble/narrative_importance.yaml` | Read-only GM salience list; absent → no outlook blocks, not an error |
| `party`, `planning_notes`, `speculations` | str | see YAML | Copy-section sources, lifted out of `SPECS` (research D1) |

Declared here rather than read from `ensemble.yaml` — a cross-service config read is the defect
`_backend_flags` was deleted for (FR-003, research D5).

### `ProjectionOutput`

| Field | Type | Default | Rules |
|---|---|---|---|
| `sections_dir` | str | `docs/grounding_sections` | Per-section files, each carrying its `inputs-sha` stamp |
| `draft` | str | `docs/projections/{doc}_draft.md` | Must contain `{doc}`; validated at load. Own namespace (research D13) |
| `legacy_draft` | str | `docs/{doc}_draft.md` | The pre-move path the FR-007b gate checks. Present so the gate is declared, not hardcoded |
| `recent_events` | str | `docs/recent_events.md` | **Moved from `ensemble.yaml`'s `paths.recent_events_out`** (research D15) — `build_recent_events` wraps the event spine, so its output belongs to this service. **Exempt from FR-005's own-subdirectory rule**: it is a promoted-style grounding artifact other pipelines already read at this path, not a draft awaiting comparison, and it is outside the legacy-gate's scope for the same reason |
| `recent_events_window` | int | `0` | **Moved from `ensemble.yaml`'s `tuning.recent_events_window`.** `0` = all chapters. Distinct from `dossier_recent_window`, which stays with the shared service |

**Retired keys in `ensemble.yaml`** (research D15): `paths.recent_events_out` and
`tuning.recent_events_window` are **deleted from `EnsembleConfig` with no compatibility shim**. Both
live campaigns carry `recent_events_out` today, so their ensemble page returns `400` until the key
is removed by hand — intended and visible, per the single-user migrate-and-delete rule. The error
must name the key and say to delete it. The server still boots; only that page is affected.

### `selection`

`campaignlib.selection.ModelSelection`, empty = inherit the platform tier. Declared now so the route
phase resolves through `resolve_selection` rather than inventing a sixth spelling (feature 003).

### Validation rules

1. Unknown key anywhere → `ValidationError` (FR-011).
2. `output.draft` without `{doc}` → `ValidationError`.
3. Absent file → all-defaults: identical *content* to today, at the new declared location (FR-012,
   SC-006 — the output namespace and the legacy gate are the two intended deviations).
4. No field may be empty-string as a way of meaning "unset" — absent means default.

## 2. Durable entities (existing; shape unchanged)

### Fact-corpus record — produced by Extraction & State

The contract State Projection depends on (research D3). Per-fact keys actually read:

| Key | Read by | Meaning |
|---|---|---|
| `type` | both | `event` → spine; `thread` → registry proposals; other types ignored |
| `fact` | both | The statement itself |
| `subject` | thread_registry | Thread title, matched by exact normalised title/alias — never similarity |
| `scene_index`, `quote_offset` | event_spine | Ordering within a chapter; absent sorts last |
| `source_quote`, `quote_verified` | both | Provenance; an unverified quote is dropped, not repaired |
| `source` | both | `{kind, session}` lineage stamp from the merge step |

**Lifecycle**: produced per chapter; replaced wholesale when that chapter is re-extracted; chapters
absent from a run keep their rows. **Invariant**: a key rename upstream must fail a test, not shrink
output (FR-004, SC-010).

### Event-spine row — `stores.events`, one JSON object per line

`{chapter, scene, seq, event, quote?, source?}`. Derived-but-durable: never hand-edited, any chapter
rebuildable from the corpus. Per-chapter replace on update; deduplicated within a chapter on a
normalised prefix of the event text.

### Thread registry entry — `stores.thread_registry`

`{id, title, status, opened, tracker?, aliases[], log[]}` with `status ∈ {open, dormant, resolved,
abandoned}`. Transitions are GM verbs only; resolving requires a chapter. Every save runs `check`.
Proposals live separately with `pending | ratified | rejected | deferred`, and a ruling survives
re-proposal.

### Section file — under `output.sections_dir`

Opens with `<!-- section: NAME | inputs-sha: HASH -->`. The hash covers the exact input bytes; the
section is stale iff recomputing differs. **Content-derived, never mtime** (FR-018, #137). Modes:
`synthesis`, `spine`, `threads`, `emerging`, `tracking`, `npc_outlook`, `copy` — which sections exist
and which document they belong to stays in code (FR-014).

### Draft — `output.draft`

Assembled from section files. Terminal state for the system; the GM diffs and promotes by hand
(FR-024). Guarded on write by the legacy-draft gate (FR-007b).

## 3. Relationships

```
fact corpus ──┬─→ entity dossiers ──→ inputs.dossiers ──┐
              │      (Extraction & State)               │
              ├─→ events.jsonl        (stores.events) ──┤
              └─→ thread_proposals ─→ thread_registry ──┼─→ section files ─→ draft
                                                        │   (sections_dir)   (output.draft)
        docs/tracking*.txt, party.md, notes ────────────┘
```

Every arrow into a section file is hashed into that section's `inputs-sha`, with one deliberate
exception: the spine **window** is context for the NPC-outlook blocks but is not hashed, so a chapter
in which an NPC did nothing re-renders nothing.
