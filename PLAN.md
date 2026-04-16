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
chapters of `docs/NeverwinterExpansionismAndTheNorth.md` using
`--split-chapters "# Chapter"` — the canonical level-1 chapter boundary in
this campaign.

**Chunk distribution:** 36 chapters, sizes 2.7K – 54K, avg 13.8K. Much more
even than the existing baselines (distill=32 files at char-count, state=9
at char-count, planning=36). Chapter boundaries are finer-grained than
"session" boundaries — a single play session sometimes spans two chapters.

| Chapter | Size | Title |
|---|---|---|
| 10 |  9.6K | The stag, the brambles, the wolves, and the pool |
| 15 | 21.3K | Deals with Harbin, and Sister Kayla, and no deal with Jenna |
| 25 |  6.4K | From Out-of-Phase Dwarves to Mechanical Mysteries |

### What worked

1. **Schema is robust across chapter sizes.** Output was well-formed for
   all three chapters. Small chapters correctly omit empty sections; larger
   chapters populate all relevant sections with reasonable depth.
2. **Cross-cut captured cleanly.** Each extract produced named sections as
   designed (NPCs / Factions / Party / Quests & Threads with status labels
   / Locations / Events / Arc Score Events / Revealed Information).
3. **One file per chapter is genuinely easier to review** than three
   (`distill_extractions/` + `state_extractions/` + `planning_extractions/`)
   separate files for the same span.
4. **Chapter-aligned chunking produces clean, even chunks** — this was the
   key unknown. The `# Chapter` splitter works. 36 chunks × avg ~14K each
   is a sweet spot for both API cost and human review.

### What to keep an eye on

1. **Chapter granularity is finer than session granularity.** A session
   can span two chapters (e.g. the Axeholm session = chapters 24 + 25 +
   26). Baseline `distill_extractions/extract_025.md` bundled a whole
   session into one extract and captured Chief Accountant + Aletra at the
   end; my chapter-25 extract stops before those beats because they're in
   chapter 26. **This isn't a bug** — the synthesizer reads all chapters
   and will cross-reference — but it does mean the raw per-chapter
   extract is less narratively complete than the baseline per-session
   extract. Downstream docs should still be fine.
2. **`--max-tokens` headroom.** Default bumped to 32K so dense chapters
   (max observed input 54K) have ample room; the schema has eight sections
   and an over-extract posture, so generous headroom is cheap insurance.
3. **Character asides and per-session sub-structures** (`## Summary`,
   `## Memorable Moments`, `## Soma`) at level-2 are *inside* chapters
   under the `# Chapter` splitter — they don't create spurious boundaries.
   This vindicates the level-1 convention for this campaign.

### Quality comparison vs baseline

Spot-check of chapter 10 (Whispering Wood / Shimmering Stag) against
`distill_extractions/extract_010.md`:

- **Both capture:** stag's territorial behavior + planar instability,
  teleporting antlers, bramble thicket combat, wolves with glowing eyes,
  pool visions (Vukradin's "numbers" quote, Brewbarry's "both sides"
  vision), stag's mention of "other nice people" who didn't return.
- **Baseline captures, unified extract doesn't:** Adabra referenced as a
  past presence, slightly more motivation detail per PC, explicit faction
  listing for Party, a "Threads & Mysteries" closing section with more
  open questions.
- **Unified extract captures, baseline doesn't:** cleaner Arc Score Events
  section (Planar Distortion flagged explicitly as a triggered arc),
  tighter event timeline, consolidated Revealed Information.

Net: roughly equivalent coverage, different format. No critical misses on
the unified side. The baseline's extra detail is mostly per-PC narrative
that the synthesizer can re-derive from the Party section.

### Go / no-go

**Proceed.** The core hypothesis — *one structured extract per chapter,
three synthesizers consuming it* — is validated on real data:

- Schema works.
- Chapter-aligned chunking with `# Chapter` is the right convention for
  this campaign (and the convention generalizes — other adventures should
  use `# Chapter` too; if not, it's a per-campaign config).
- Chunk sizes are naturally reasonable without a smart chunker.
- Coverage quality is comparable to baseline.

## Phase 3: wired (2026-04-15)

All three synthesizers gained an additive `--chapter-extracts DIR` flag.
No existing flags, functions, or prompts were modified — the new path is
strictly parallel:

- `distill.py`: `SYNTHESIZE_FROM_CHAPTERS_SYSTEM` + `run_synthesize_from_chapters()`.
- `campaign_state.py`: `SYNTHESIZE_FROM_CHAPTERS_SYSTEM_BASE` + `build_synthesize_from_chapters_system()` + `run_synthesize_from_chapters()`. `--track-file` still applies to the synthesize-time Tracked Items Status overlay.
- `planning.py`: `SYNTHESIZE_FROM_CHAPTERS_SYSTEM` + `run_synthesize_from_chapters()` (also accepts the usual `--npc`, `--arc-scores`, `--context`).

Each new prompt enumerates the shared schema, names the sections it cares
about, and explicitly calls out the sections it treats as incidental
context. This keeps the three synthesizers focused on their own angle while
sharing the extract file set.

**Smoke test:** `distill.py --chapter-extracts` run on the three POC
chapter extracts produced a clean `world_state.md` with sections `NPCs /
Factions / Locations / Events Canon Timeline / Threads & Mysteries /
Revealed Information` — exactly the consumer map from the design above.
Error paths validated for missing directory and empty directory on all
three scripts.

## Phase 4 results (2026-04-15): regression

Full 36-chapter extract generated; all three synthesizers run end-to-end
against the full set; outputs compared to baseline docs.

| Doc | New lines | Baseline lines | Verdict |
|---|---|---|---|
| `world_state.md`    | 193 | 268 | Major regression |
| `campaign_state.md` | 207 | 311 | Regression |
| `planning.md`       | 109 | 513 | Major regression |

**world_state.md** — lost the "The Party" section entirely (per-PC block
with location / faction / motivations / traits / secrets / relationships)
and the "Items & Artifacts" section. Root cause is prompt design: the new
`SYNTHESIZE_FROM_CHAPTERS_SYSTEM` explicitly tells distill that `## Party`
and `## Arc Score Events` are "incidental context". That is wrong for
world_state — the Party block is the document's anchor.

**campaign_state.md** — structure preserved. NPC Current States table
dropped from 40 rows to 23 (Gnomengarde NPCs, Tower of Storms NPCs,
Axeholm antagonists, Carver lieutenants missing). Per-encounter tactical
detail collapsed to one-liners. Party-resource inventory (Necklace of
Fireballs, Wand of Secrets, Midnight Tears vials, etc.) gone. Tracked
Items Status retained the bulk of entries but lost forensic nuance like
"NOT FOUND AS DESCRIBED" reconciliations.

**planning.md** — 5 NPC dossiers vs 17 in baseline. Only 4 factions vs
10. Threat Tracker values are guessed ("6–8 estimated") rather than
carried from the arc-score docs. The 103 NPC dossier files and 8
arc-score docs were passed in (same as baseline) but the synthesize pass
summarized aggressively and dropped the long tail.

### Root causes

1. **Per-chapter extract breadth comes at a per-entity depth cost.** The
   unified schema has 8 sections; each chapter's NPC section is terser
   than a dedicated NPC-only extract would be. Synthesis across 36
   chapters then reconstructs per-NPC views from fragments — and when
   told to "be concise" the model cuts the long tail.
2. **Synthesize prompts are too compressing.** They describe sections
   rather than demanding enumeration. Baseline prompts produce longer
   output from richer extracts; the new prompts produce shorter output
   from terser extracts — compounding the loss.
3. **Design error on distill.** Treating Party as incidental context was
   wrong. world_state must have a Party anchor.

### Remediation options (not yet tried)

- **Prompt fixes only** (cheap, reversible):
  - `distill.py`: reinstate a Party section; add Items & Artifacts.
  - `planning.py`: demand one subsection per NPC that appears in any
    chapter extract, no filtering; demand Threat Tracker values read
    directly from the arc-score docs, not inferred.
  - `campaign_state.py`: demand the NPC Current States table enumerate
    every named NPC; demand per-encounter tactical entries match the
    baseline's granularity.
- **Extract-schema additions** (more invasive):
  - Add `## Items & Artifacts` section to `chapter_extract.py` schema.
  - Add `## Player Characters` or fold PC beats more assertively.
- **Kill the branch** per the stated kill criteria: "If at any phase the
  unified extract produces systematically worse synthesis — missed NPCs,
  dropped arc score triggers, lost party acquisitions — abandon."

The current outputs meet the kill criteria. Before pulling the plug, one
round of prompt-only fixes is cheap to try (no new extracts needed —
`chapter_extracts/` is cached) and will disambiguate prompt-level
compression from architectural loss.

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
