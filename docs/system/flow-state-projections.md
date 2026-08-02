# The State-Store + Projection Flow (#213, Phases 0–4)

> Written 2026-07-31, as Phases 0–4 landed. Audience: anyone wiring the UI
> (or a skill) to the new flow. Companion to `flow-ensemble.md`, which
> describes the extraction ensemble this flow builds on.

## The one-paragraph architecture

Authored + verified **state stores** on disk; grounding docs are
**projections** of them. Extraction reads the highest-fidelity artifact
that exists per chapter (not uniformly the prose), every fact carries its
source lineage, and each downstream document section re-renders only when
the bytes of its input store change. Every precision decision — chapter↔
session joins, thread identity, NPC salience, dossier merges, draft
promotion — ends at a GM checkpoint. LLM calls are explicit; a build
without `--backend` is deterministic by definition and spends nothing.

## End-to-end flow

```
session artifacts                       CHAPTER IDENTITY (Phase 0)
  summaries/YYYYMMDD/                     assemble.py --chapter N   -> frontmatter minted
    session-summary.md                    release append            -> <!-- chapter | session --> marker
    scene_extractions_new/*.md            split_chapters.py         -> frontmatter landed + LOUD check
      (+ .reviewed markers)               renumber_chapters.py      -> one-time fix (done for Phandalin)
    gm-assist.md, VTTs                    summary_map.yaml          -> chapter<->session join, GM-approved rows ONLY
        |
        v
SOURCE-LINEAGE LADDER (Phase 1)         ensemble_batch.py --source auto
  reviewed scenes > structured            resolve_source() per chapter, gated on approved map rows
  summary > chapter prose                 lineage.json + composed lineage_scenes.md in the workdir
  per-lens routing (1.1):                 plan_resolved.yaml: interiority lens ALWAYS reads chapter prose
        |
        v
EXTRACTION (Phase 1.2 prompts)          5 lenses; prompts ask for `entity` (never a headline);
                                          state changes write twice (event + entity-filed fact)
        |
        v
per_chapter/<stem>/merged.json          ensemble_merge.py stamps per-fact source:
  facts with source lineage               {kind: scenes|summary|chapter|mixed[, session]}
        |
        +--------------------+---------------------------+
        v                    v                           v
EVENT SPINE (Phase 2)     THREAD REGISTRY (Phase 3)    DOSSIERS (existing)
  event_spine.py update     thread_registry.py propose   facts_to_state.py --list  <- scope checkpoint
  docs/ensemble/            thread_proposals.yaml        state_dossiers/ -> /ensemble-alias-review
    events.jsonl              (pending, GM triages)        -> /ensemble-type-merge -> merged_dossiers/
  (chapter, scene, seq)     thread_registry.yaml           (GM-confirmed curation; REVIEW Uncertainty)
  + quote + lineage           (GM-ratified canon)
        |                   thread_registry.py speculate
        |                     -> notes/ (NOT canon — idea surface)
        v                    v                           v
GROUNDING SECTIONS (Phase 4)            grounding_sections.py build --doc <doc>
  docs/grounding_sections/<doc>/*.md      each section: <!-- inputs-sha --> content stamp
        |                                 re-render IFF input bytes changed (#137 principle)
        v
docs/<doc>_draft.md                     assembled; GM diffs + promotes (gate unchanged)
```

## The stores

| store | file | written by | read by | gate |
|---|---|---|---|---|
| Chapter identity | frontmatter in `docs/chapters/*.md` | `split_chapters` / `renumber_chapters` | everything | split refuses on counter disagreement |
| Chapter↔session join | `docs/ensemble/summary_map.yaml` | `summary_map.py` (proposes) | lineage resolver | `approved: true` per row, GM only |
| Fact corpus | `per_chapter/<stem>/merged.json` (+ `lineage.json`) | ensemble | spine, dossiers, threads | `--list` / `--coverage` checkpoints downstream |
| Event spine | `docs/ensemble/events.jsonl` | `event_spine.py update` | recent_events + campaign_state section | derived-but-durable; per-chapter replace; never hand-edited |
| Thread canon | `docs/thread_registry.yaml` | `thread_registry.py` verbs | planning sections, NPC outlook | every row GM-ratified; `check` on every save |
| Thread harvest | `docs/ensemble/thread_proposals.yaml` | `thread_registry.py propose` | planning "emerging" section; triage | all `pending` until GM rules; rulings preserved |
| Speculations | `notes/thread_speculations.md` | `thread_registry.py speculate` | the GM's eyes only | NOT canon; no pipeline reads it |
| Entity dossiers | `state_dossiers/` → `merged_dossiers/` | `facts_to_state` → type-merge skill | synthesis sections, NPC outlook | alias-review + type-merge skills; hand-review of Uncertainty |
| Sections | `docs/grounding_sections/<doc>/*.md` | `grounding_sections.py` | assembly | inputs-sha staleness; no implicit LLM spend |
| Drafts | `docs/<doc>_draft.md` | assembly | the GM | diff → promote by hand (unchanged) |

## Tool reference (new or changed)

### Phase 0 — chapter identity

- **`assemble.py --chapter N [--session YYYYMMDD]`** — mints identity
  frontmatter (`chapter`/`session`/`title`) at session-doc assembly;
  session date auto-derived from the `summaries/YYYYMMDD/` path.
- **`split_chapters.py`** — consumes the inline
  `<!-- chapter: N | session: YYYYMMDD -->` marker under each bible heading
  into split-file frontmatter; **refuses to write anything** when a heading
  number or marker disagrees with file position. `--no-check` only for
  legacy decimal-numbered bibles.
- **`renumber_chapters.py --bible … --chapters-dir … [--summary-map …] [--apply]`**
  — the one-time in-place fix (dry-run default, idempotent). Stamps
  `session:` only from approved map rows. Reports hand-edit drift, never
  overwrites it.
- **`summary_map.py`** — unchanged; its `approved:` rows are the sole join
  authority. UI note: row approval is a first-class GM action.

### Phase 1 — source lineage

- **`ensemble_batch.py --source auto|chapter [--campaign-dir D] [--summary-map F]`**
  — walks the ladder per chapter. `--lineage-report` prints the decision
  table (chapter → source kind → session → reason) with **no model calls** —
  the UI's preview surface before an extract run.
- **`campaignlib.lineage`** — `resolve_source()` (deterministic ladder:
  reviewed scenes majority > structured summary > chapter; every rung above
  chapter needs an approved map row), `compose_scenes()` (frontmatter-
  stripped concatenation), `route_plan()` (per-lens documents; interiority
  is chapter-bound), `CHAPTER_BOUND_PASSES`.
- **Workdir artifacts**: `lineage.json` (the decision + per-pass kinds),
  `lineage_scenes.md` (the composed input), `plan_resolved.yaml` (per-lens
  routing). All auditable after the fact.
- **`ensemble_merge.stamp_lineage`** — per-fact
  `source: {kind[, kinds][, session]}`; cross-source merges stamp the
  honest `mixed` list; absent lineage stamps nothing.
- **Lens prompts (1.2)** — ask for `entity` (never an event headline; the
  action goes in `fact`); the three factual lenses carry the
  **state-changes-write-twice** rule; `parse_facts_block` normalises
  `entity`→`subject` so merged.json is unchanged.

### Phase 2 — event spine

- **`event_spine.py update --corpus GLOB [--store F]`** — replaces rows for
  chapters present in the corpus, preserves the rest. Rows:
  `{chapter, scene, seq, event, quote, source}`; only `quote_verified`
  quotes count as provenance.
- **`event_spine.py render [--window N] [--output F]`** — projects
  `recent_events.md` from the store.
- **`build_recent_events`** — kept as a CLI-compatible wrapper
  (update + render); existing server route untouched.

### Phase 3 — threads

- **`thread_registry.py propose --corpus GLOB`** — deterministic harvest of
  `thread` facts → `thread_proposals.yaml`, matched against the registry by
  exact normalised title/alias (never similarity). GM rulings
  (`ratified`/`rejected`/`deferred`) survive re-proposes.
- **Verbs** — `add`, `log`, `set-status`, `alias`: the validated writers a
  triage UI/skill drives. Statuses `open|dormant|resolved|abandoned`;
  resolving needs `--chapter`; every save passes `check`.
- **`render`** — the projection. `[ch00]` and duplicate threads are
  impossible by construction.
- **`speculate --backend … --model …`** — the ONE LLM surface, and the one
  place invented connections are the assignment. Output to `notes/`;
  clearly headed NOT CANON; rejected proposals never feed it.

### Phase 4 — sections

- **`grounding_sections.py list --doc D`** — staleness table
  (`fresh`/`stale`/`unbuilt`/`no-input`) — the UI's status surface.
- **`grounding_sections.py build --doc D [--sections a,b] [--force]
  [--backend …] [--npcs a,b] [--window N] [--dossiers-dir D]`** — renders
  stale sections, assembles `docs/<doc>_draft.md`.
- **Section map**: `world_state` = npcs/factions/locations/world (synthesis
  over type-scoped `merged_dossiers` globs); `campaign_state` =
  recent_events (spine) + **tracking** (module-progress audit) + party
  (copy); `planning` = threads → emerging → npc_outlook → speculations →
  factions → notes (the threads-at-play cockpit, layered by certainty).
- **Tracking audit** (`campaign_state`): every `docs/tracking*.txt` item
  judged against the full event spine — DONE / PARTIAL / NOT SEEN with
  chapter citations and per-section counts (prompt:
  `config/agents/tracking_completion.md`). LLM-proposed, GM-verified line
  by line at the draft gate; module divergence is PARTIAL-with-explanation,
  never a silent DONE; NOT SEEN never speculates. Re-renders when a
  tracking list or the spine changes.
- **Freshness**: every section file opens with
  `<!-- section: NAME | inputs-sha: HASH -->` — hash of the exact input
  bytes. Content-derived, never mtime.
- **Guards**: synthesis sections skip without `--backend` (no implicit
  spend); zero matching dossiers skips cleanly; missing required input is
  a loud error.
- **NPC outlook** — per-NPC blocks (Status / Active plans / What party
  knows / Hidden / Key leverage / Arc score). Selection = GM salience
  (`--npcs` or `npc_*` in `narrative_importance.yaml` force_include).
  Inputs = the NPC's **ensemble** dossier (`merged_dossiers` falling back
  to `state_dossiers`; `docs/npcs/` is the retired build-dossiers path)
  + thread registry; spine window is context but unhashed. Each block has
  its own inputs-sha — a chapter where the NPC did nothing re-renders
  nothing. Prompt: `config/agents/planning_npc_outlook.md`.

## The GM checkpoints a UI must surface

1. **Summary-map row approval** (Phase 0) — evidence view + approve toggle.
2. **Lineage report** (Phase 1) — read-only preview of per-chapter source
   decisions before an extract run.
3. **`facts_to_state --list` / `--coverage`** — bundling scope + hearsay
   flags (existing).
4. **Alias review / type merge** (skills today) — state→merged dossier
   curation.
5. **Thread triage** — walk `thread_proposals.yaml`, drive the registry
   verbs. (Planned as a skill; a UI can drive the same verbs.)
6. **Section staleness + per-section rebuild** — `list` + `build
   --sections`, with explicit backend choice for synthesis sections.
7. **Draft promotion** — unchanged diff → copy.

## Known seams and gaps (honest list)

- **`planning.py` and `grounding_sections.py` both write
  `docs/planning_draft.md`.** Until planning.py is retired/wrapped, do not
  run both; the sections build is the forward path.
- **Phandalin has no `merged_dossiers/`** — the type-merge skill has never
  run there; everything falls back to `state_dossiers/` (includes
  location-scoped fragments).
- **Spine near-duplicates** — several lens phrasings of one beat survive
  the 60-char dedup key; tuning knob, not yet addressed.
- **Quote offsets across split sources** — offsets are computed against one
  reference document per chapter; facts from the other document lack
  position stamps (consumers tolerate absence).
- **NPC outlook payload** — the spine-window context dwarfs the dossier
  (~66KB vs ~5KB); filter-to-mentions is the obvious cheap refinement
  before large salience lists.
- **Phase 5 (verification) not yet wired** — mechanical checks + the
  cross-model verifier were validated in the #212 experiments; per-fact
  `source` stamps exist precisely so the verifier can pick the right
  ground truth per claim.
- **Chapters 10 and 33 (Phandalin)** have no `merged.json` (incomplete old
  runs) — visible as gaps in the spine store.
