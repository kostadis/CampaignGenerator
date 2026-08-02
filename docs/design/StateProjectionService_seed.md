# Spec-kit seed: State-Projection Rendering as its own service

**Date**: 2026-08-01 | **Companion**: `StateProjectionService_research.md`

The research payload beside this file exists so a spec-kit run does not re-derive facts that have
already been established. Run the phases below in order; the only manual step is copying the
research file into the feature directory once it exists.

## 0. Prerequisites

Speckit's skills are gitignored, so a fresh worktree has `.specify/` (templates, scripts,
constitution) but no `.claude/`. Already fixed in this checkout by copying **only** the skills
directory:

```bash
cp -r /home/kroussos/src/CampaignGenerator/.claude/skills .claude/skills
```

Do **not** copy `.claude/` wholesale — the main checkout's `.claude/worktrees/` is 93 MB.

Skills load at session start, so `/speckit-*` will not resolve until a **new session** is started in
this directory.

## 1. `/speckit-specify`

Paste this as the feature description:

> Split the campaign's document-generation into four explicit services and give the newest one its
> own configuration and UI.
>
> `ensemble_batch` + `facts_to_state` become a shared **Extraction & State** service producing the
> fact corpus and the per-entity dossiers. Two rendering services consume that state and are
> siblings, neither depending on the other: **dossier synthesis** (`synthesise_world_state` and the
> `--synthesize-only` staging) and **state projection** (`event_spine`, `thread_registry`,
> `grounding_sections`). A third rendering path — the per-tool API path (`distill`,
> `campaign_state`, `party`, `planning`) — keeps its own extraction and its own config.
>
> Each rendering path must write its documents into its own directory so the three can run in any
> order, side by side, without overwriting each other or feeding each other by accident.
>
> The state-projection service gets a strict config document of its own and a UI layer surfacing its
> GM checkpoints: summary-map row approval, the lineage report, section staleness with per-section
> rebuild, thread triage over `thread_proposals.yaml`, and draft promotion.

Suggested `--short-name`: `state-projection-service`.

## 2. Copy the research payload in

`create-new-feature.sh` picks the next free number and writes the real path to
`.specify/feature.json` — so read the path rather than assuming `006`:

```bash
FEATURE_DIR=$(python3 -c "import json;print(json.load(open('.specify/feature.json'))['feature_directory'])")
cp docs/design/StateProjectionService_research.md "$FEATURE_DIR/research.md"
```

(The file currently still points at `specs/005-ui-batch-selection` — `/speckit-specify` overwrites
it, so run the copy *after* that phase, not before.)

Tell `/speckit-plan` to **extend** the existing `research.md`, not regenerate it.

## 3. `/speckit-clarify` — the open questions

These are deliberately unanswered. They are genuine design forks, not gaps in the survey.

- **Q1** — Now that extraction is its own service, does its config split out of `ensemble.yaml`
  (a new document, leaving `ensemble.yaml` to path 2's renderer), or does `ensemble.yaml` stay the
  shared document and path 2's renderer get the new one?
- **Q2** — `synthesise_world_state` is invoked by both path 2 and path 3
  (`grounding_sections.py:368`). Does it move to the shared service, get duplicated, or stay path-2
  code that path 3 execs?
- **Q3** — R3's concrete layout: which directory per path, and does `campaign_state.py:130`'s
  auto-stage of `world_state_draft.md` follow path 2 to its new location or get retired?
- **Q4** — Does the shared service's own GM curation (`narrative_importance.yaml`, alias review,
  type merge) surface in path 3's UI, in its own UI, or stay CLI/skill-only?
- **Q5** — Scope of R5: the full set of GM checkpoints in one page, or section staleness + rebuild
  first and the rest later?

## 4. Remaining phases

`/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.

`/speckit-analyze` should test the plan by name against all ten principles of
`.specify/memory/constitution.md` v1.2.0. The four most likely to bite:

- **II (human checkpoint)** — R5 adds UI to a pipeline full of precision decisions; every checkpoint
  the flow doc lists must remain a gate, not a button that runs the next stage.
- **VI (CLI is the engine)** — the new routes shell out; they must not reimplement projection logic.
- **X (no silent "all")** — the chapter set stays explicit at every layer (research D6).
- **I / VII** — the state stores stay on disk as truth, and no phase may collapse the narrow
  per-section passes into one wide pass (`ChapterExtractConsolidation_killed.md`).

## 5. Did the seed work?

The generated `spec.md` should need **no** new codebase archaeology: every file:line it cites should
already appear in `research.md`. If `/speckit-plan` re-derives the literal inventory, the fact-record
keys, or the section-dependency table, the seed was incomplete — fold what it had to rediscover back
into `docs/design/StateProjectionService_research.md` so the next run starts further ahead.
