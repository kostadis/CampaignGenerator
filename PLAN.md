# Chapter-Aligned Extract Consolidation — Design Proposal

**Status:** Draft. No code changes yet. Feature branch is a landing pad for the
design review and any proof-of-concept work.

## Motivation

Three scripts — `distill.py`, `campaign_state.py`, `planning.py` — independently
scan the same `summaries.md` during their extract phase. Each chunks the input
(all three default to 60K chars), asks Claude to pull out overlapping categories
of information (NPCs, factions, events, etc.), and writes per-script extraction
intermediates to disk.

Chapter-aligned splitting is already available via
`campaignlib.prepare_chunks(split_chapters=...)`. When a campaign uses chapter
splitting, each chunk corresponds to a logical unit (one session, one arc). That
makes it feasible to replace three focused scans of every chunk with **one rich
extract per chapter**, consumed by three focused synthesizers.

Expected wins:
- ~3× reduction in extract-phase token cost (one API call per chapter instead
  of three).
- One human-reviewable artifact per chapter instead of three.
- A reusable per-chapter extract that can feed future tools (`query.py`,
  `npc_table.py`, etc.) without adding more scan passes.

## Current state

### Per-script extraction focus

| Script | Extract focus | Extract dir |
|---|---|---|
| `distill.py` (L25–53) | Canon lore: NPCs, factions, world events, locations, threads/mysteries | `distill_extractions/` |
| `campaign_state.py` (L66–106) | Completion: finished quests, NPC state changes, party acquisitions, current situation | `state_extractions/` |
| `planning.py` (L51–80) | Tactical: NPC activity, faction movements, arc score triggers, whereabouts | `planning_extractions/` |

All three read the same `summaries.md`, produce structurally similar output
(named sections with bulleted facts), and feed a synthesize pass that emits the
final doc.

### Out of scope

- **`party.py`** — player-character domain, not NPC/world. Stays on its own path.
- **`vtt_summary.py`** — VTT transcript input, upstream of `summaries.md`. Stays.
- **`planning.py --build-dossiers`** — already a single-extract-many-output
  pattern for a different purpose (per-NPC dossier files). Stays.
- **`session_doc.py`** — consumes `roleplay_extractions/` (from
  `vtt_summary.py`), not `summaries.md`. Out of scope, but noted below.

## Proposed design

### New script: `chapter_extract.py`

One pass per chapter, producing a structured intermediate with explicit named
sections. The extract prompt is a checklist, not free-form — the model works
through a template so nothing gets dropped under a vague "extract everything
important" instruction.

### Shared extract schema (one file per chapter)

```markdown
<!-- chapter: <N>, source_session: <session id> -->

## NPCs
For each named NPC (not a PC): identity, faction, actions taken, dialogue beats,
state changes (died, allied, fled, revealed identity), last known location.

## Factions
For each faction: visible actions, alliances shifted, resources gained/lost,
members mentioned.

## Party
Actions, decisions, acquisitions (items / titles / intel / reputation),
arc score moments, relationship beats.

## Quests & Threads
One bullet per thread: opened / progressed / resolved — include outcome where
applicable.

## Locations
Visited, revealed, or changed — current state if modified.

## Events
Chronological bullets of significant events (tactical, social, environmental).

## Arc Score Events
Specific moments matching tracked threat arcs. Name the arc, describe the
trigger.

## Revealed Information
Secrets, plans, or intel the party learned that matter downstream.

## Tracked Items
(Optional; only populated if `--track-file` is passed.) Each tracked item MUST
be addressed if it appears in this chapter — "yes, and what happened" or
"no mention".
```

Output: `chapter_extracts/extract_<NNN>.md`, one file per chapter. Sharded
across all three downstream scripts; the directory is the canonical shared
artifact.

### Synthesizer changes

Each of the three scripts gains a `--chapter-extracts DIR` flag:

- If set, skip the extract pass entirely. Read the shared directory, feed the
  union of its contents into synthesis.
- Synthesis prompt is tightened: each script is told which sections of the
  schema it cares about and how to interpret them. Sections it doesn't need are
  ignored (not removed — a section may still contain incidental context).
- Existing `--synthesize-only` + `--extract-dir` path is untouched, keeps
  working for campaigns that aren't using chapter splits.

Consumer map:

| Script | Primary sections consumed |
|---|---|
| `distill.py` | NPCs, Factions, Locations, Events, Quests & Threads, Revealed Information |
| `campaign_state.py` | Quests & Threads (resolved only), NPCs (state changes), Party (acquisitions), Tracked Items |
| `planning.py` | NPCs (activity), Factions, Arc Score Events, Revealed Information |

### Backward compatibility

- No existing flag is removed or changed.
- `--chapter-extracts` is purely additive.
- If a campaign never produces `chapter_extracts/`, all three scripts behave
  exactly as today.

## POC results (Phandalin, 2026-04-15)

A minimal `chapter_extract.py` was built to the schema above and run on three
chunks of `docs/NeverwinterExpansionismAndTheNorth.md` using
`--split-chapters "## "`:

| Chunk | Size | Content |
|---|---|---|
| 10 | 5.5K | `## Soma` — gnome kings politically destabilized, Triboar play reveal |
| 15 | 2.2K | `## 05-01 Taraksh 1495` — Vukradin's impulse to destroy the lighthouse |
| 25 | 73K  | `## 09-02- Taraskh 1495` — Axeholm dungeon + gold mine + Phandalin wrap |

### What worked

1. **Schema is robust across chunk sizes.** Output was well-formed for the 2K
   tiny scene, the 5K medium scene, and the 73K bundled multi-session chunk.
   Empty sections were correctly omitted for small chunks; all sections
   populated on the large one.
2. **Cross-cut captured cleanly.** Chunk 25 produced the expected unified
   output: NPCs, Factions, Party, Quests & Threads with status labels,
   Locations, Events, Arc Score Events, Revealed Information.
3. **One file per chunk is genuinely easier to review** than three
   (`distill_extractions/` + `state_extractions/` + `planning_extractions/`)
   files for the same span.

### What surfaced as concerns

1. **Chunking convention matters more than expected.** Naive `## ` splitting
   produced **65 chunks** on the Phandalin summaries — versus distill's
   **32**, state's **9**, and planning's **36** on the same source. Chunks
   are wildly uneven: some are sub-session headings (`## Soma`,
   `## Summary`, `## Spells`), some are whole multi-day bundles at 73K.
   The schema works but the *chunk boundaries* need engineering.
2. **Large chunks lose detail at `max_tokens=8096`.** Chunk 25 at 73K
   produced **more breadth, less depth** than distill's baseline for the
   same source span. Distill had split this span into 7 smaller files, each
   extracted deeply; the unified extract covered all the same NPCs and
   events but with fewer descriptive details per entity. The 8K output cap
   is the bottleneck on rich sessions.
3. **Baseline has its own blind spots.** `distill_extractions/extract_025.md`
   covers the Axeholm dungeon in extreme detail but misses the next-door
   content (gold mine negotiation, Don-Jon murder, Harbin's 250 gp payment,
   Teega's recovery, Big Al / Qelline reconciliation) which landed in
   distill's extract_026–028. The baseline is split-and-dense; the new
   approach is unified-and-broad. Neither is strictly better in isolation —
   the synthesizer pass is what reconciles.

### Engineering implications

- Need a **smart chunker** that targets ~30–40K per chunk. Merge tiny
  sub-session fragments into their parent session. Subdivide oversized
  multi-day bundles. Don't use raw `## ` splits.
- Bump `--max-tokens` default for the extract pass. 16K–32K would cost
  little more and capture significantly more detail on long sessions.
- Document a canonical chapter-boundary convention per campaign. The
  Phandalin summaries mix session date-stamps, per-session sub-structures
  (Summary / Memorable Moments / Scenes), and character asides (`## Soma`).
  The splitter cannot distinguish these without cleaner input markers.

### Go / no-go

The core hypothesis — *one structured extract per chapter, three
synthesizers consuming it* — is validated at the **schema** level. Output
format is clean and the human-review story genuinely improves. The POC also
shows the work splits into two threads:

- **Schema design:** done.
- **Chunker engineering:** still needed.

Recommend proceeding to Phase 3 (wire synthesizers) only after the chunker
produces chunks comparable in size to distill's current 32 files (~15–25K
per chunk). Otherwise the synthesizers inherit a detail deficit they can't
recover from.

## Implementation phases

### Phase 1 — Build the extractor
- New `chapter_extract.py` CLI.
- Schema frozen in code with the sections above.
- Per-chapter output to `chapter_extracts/`, skip-if-exists like the existing
  extractors.
- Respects `--track-file` (inherit `campaign_state.py`'s pattern).
- Uses `prepare_chunks(split_chapters=...)` for chapter-aligned splitting;
  falls back to character-count chunking if no split pattern supplied.

### Phase 2 — Validate extract quality against baseline
- Pick one representative campaign.
- Run both the new extractor and the three existing extractors on the same
  `summaries.md`.
- Manual side-by-side comparison for one chapter. Look specifically for:
  - Subtle party acquisitions (the area `campaign_state.py` is best at).
  - Arc score triggers (the area `planning.py` is best at).
  - Obscure location and thread mentions (the area `distill.py` is best at).
- **Human review is the gate.** If the unified schema misses things the focused
  extracts catch, iterate on the schema. Do not proceed to Phase 3 until one
  representative chapter passes.

### Phase 3 — Wire synthesizers to consume the shared extract
- Add `--chapter-extracts` flag to `distill.py`, `campaign_state.py`,
  `planning.py`.
- Keep all existing flags and paths intact.
- Tighten synthesis prompts to reference the shared schema section names.

### Phase 4 — Validate end-to-end quality
- Generate `world_state.md`, `campaign_state.md`, `planning.md` from the
  shared extracts.
- Compare against baseline outputs from the current pipeline.
- Human side-by-side review of each doc. Accept or iterate.

### Phase 5 — Migration (only if Phase 4 passes)
- Update `CLAUDE.md` to document the new workflow.
- Update the UI (`server/routers/grounding.py`) to offer a single "Extract
  Chapters" action followed by three synthesize buttons.
- Keep the old direct-from-summaries paths as a fallback for campaigns that
  can't or don't want to chapter-split.

## Risks and mitigations

**Focus loss.** A broad prompt produces worse extraction than a narrow one.
- *Mitigate:* checklist-style prompt with named sections, not "extract
  everything important". Model fills each section in turn.
- *Mitigate:* over-extract — the schema captures more than any single
  synthesizer needs. Better to prune in the synthesizer than miss at extract
  time.

**Failure coupling.** Currently a miss in `planning_extractions/` doesn't affect
`campaign_state.md`. After consolidation, a miss propagates to all three docs.
- *Mitigate:* chapter granularity means each extract is small enough to read
  in full during review.
- *Mitigate:* the shared extract **is** the human checkpoint. Production runs
  that skip review are the risk; Phase 5 docs should make the review step
  explicit in the UI flow (not auto-chain extract → synthesize).

**Schema gravity.** Once three docs depend on the schema, changing it is
expensive.
- *Mitigate:* freeze the schema only after Phase 2 validation.
- *Mitigate:* include a schema version comment in every extract file, so a
  future schema change can be detected on load.

**Regression risk.** The three existing outputs have been tuned over months.
- *Mitigate:* keep the old extract paths working through Phase 5. Phase 5 is
  the only point where anything becomes a new default.
- *Mitigate:* if validation shows quality regression on one of the three docs,
  keep that script on its old path and consolidate only the ones that pass.

**LLM-pipeline rule compliance.** Global rule: *LLM extracts → human reviews →
LLM renders* is OK; *LLM extracts → LLM structures → LLM renders* is not.
- *Mitigate:* the unified extract preserves the same check-point structure as
  today. Extract lands on disk; human can review; synthesizers read from disk.
  The consolidation moves from `3 × (extract → synthesize)` to
  `1 × extract → 3 × synthesize`, but the human review point remains the
  per-chapter extract file.

## Open questions

1. **Tracked items handling.** `campaign_state.py --track-file` requires that
   listed items are addressed in the extract. Does `## Tracked Items` go into
   the shared extract (where `distill` and `planning` can ignore it), or stay
   as a `campaign_state.py`-only post-extract overlay? **Lean toward the
   former** — the information is cheap to extract once.

2. **Chapter boundary convention.** What's the canonical splitter across
   campaigns? `## Session `, `## Chapter `, a CLI-supplied regex, or
   per-campaign config? Existing scripts already accept `split_chapters`; we
   just need to pick a campaign-level convention and document it.

3. **UI integration scope.** Three grounding endpoints currently each run their
   own extract. Post-consolidation the UI could offer one "Extract Chapters"
   action followed by three synthesize buttons. Out of scope for Phases 1–4
   but a Phase 5 milestone.

4. **Session doc pipeline.** `session_doc.py` Pass 4 extracts from
   `roleplay_extractions/` (VTT-derived), a different source. Out of scope,
   but: should future per-session narrative passes also feed into
   `chapter_extracts/` for reuse?

## Success criteria

- **Phase 2:** per-chapter unified extract covers ≥95% of content the three
  focused extracts produce, by manual review of one representative chapter.
- **Phase 4:** final `world_state.md`, `campaign_state.md`, `planning.md` are
  judged equal or better than baseline by the GM, side-by-side.
- **Phase 5:** ~3× reduction in tokens spent on the extract phase, measured
  via API-call logs on one representative run.

## Kill criteria

If at any phase the unified extract produces systematically worse synthesis —
missed NPCs, dropped arc score triggers, lost party acquisitions — abandon the
branch. The existing three-scan pipeline works and the token savings are a
cost optimization, not a correctness improvement. **Correctness takes
precedence over cost.**
