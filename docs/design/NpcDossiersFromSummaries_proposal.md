# Per-NPC dossiers from session summaries — proposal

> Status: proposal (2026-10-06). Branch `research/npc-dossiers-from-summaries`.
> Grounded in the grounding-docs survey (`~/src/dgx-fun/survey-grounding/main.tex`,
> twelve approaches) and a measurement on the Out of the Abyss corpus
> (`~/out-of-the-abyss/out-of-the-abyss/docs/summaries`, chapters 2–70).

## Recommendation in one paragraph

Extend **summary-native grounding (survey approach 12)** with a per-NPC render
stage. Do not build a new extractor. Make it three steps. **(1)** Keep the
existing deterministic evidence dossiers (`summary_native build` already writes
222 NPC dossiers for OOTA, with no model call). **(2)** Add a deterministic
**scene/moment linker** that attaches every scene and memorable moment naming
the NPC, with exact registry names only. This is approach 11's contribution, and
it is where most of the missing evidence is. **(3)** Add one **render call per
selected NPC** that fills a fixed dossier template from that evidence pack, cites
chapter and scene for each claim, and writes to a drafts directory. Nothing
reaches `docs/npcs/` until the GM promotes it. Header facts (first seen, last
seen, chapters, appearance count) are computed, not generated. Rendered dossiers
are a **leaf product**: planning synthesis keeps reading the evidence dossiers,
so an unreviewed rendering never feeds another model.

## What decision is removed from the human

Only prose: compressing an NPC's evidence into a readable dossier. Every
precision decision stays out of the model:

| Decision | Who makes it | How |
|---|---|---|
| Identity (which headings / names are this NPC) | GM | Summary headings + registry exact same-type aliases. Near-duplicates are *listed*, never merged (existing `duplicates.py` / `canon.yaml`) |
| Ordering | Authored structure | Filename chapter number → scene id `NNN.SS` → line |
| Attribution | Authored structure | Observations are whole summary paragraphs, never atomised. This avoids the failure that made the ensemble report a slain antagonist as "Alive" |
| Scope (which NPCs get a dossier) | Deterministic rule or GM | Existing `select.py` rules: `--name`, recent, recurring |
| Current status | Authored structure | The latest observation is labelled as the latest. The model may not infer "alive/dead" from silence |

Checklist from the global rule: the input is human-reviewed summaries; the
model renders only; the GM reviews the draft; if a draft is 10% wrong, nothing
downstream inherits it, because drafts are not inputs to `planning synth`
unless the GM explicitly names them as reviewed. That is the same draft-chaining
rule summary-native already enforces.

## Measurement: why the linker matters

Today every observation in a summary-native NPC dossier comes from that NPC's
`## NPCs` entry, and each one says `Scene: none`. The scenes and memorable
moments, where the NPC actually acts and speaks, are not attached. The count
below is an exact word-boundary match of the NPC's registry name and aliases
against `## Scenes` subsections and `## Memorable Moments` bullets (scratch
script, no model):

| NPC | `## NPCs` entries | scenes naming them | moments naming them | sessions with entry → with any mention |
|---|---:|---:|---:|---|
| Jimjar | 33 | 71 | 17 | 33 → 39 |
| Glabbagool | 30 | 94 | 21 | 30 → 32 |
| Eldeth | 24 | 36 | 6 | 24 → 27 |
| Stool | 16 | 29 | 9 | 16 → 17 |
| Sarith | 13 | 33 | 12 | 13 → 15 |
| Buppido | 12 | 32 | 16 | 12 → 17 |
| Ilvara | 6 | 26 | 5 | 6 → 10 |
| Jorlan | 4 | 10 | 2 | 4 → 4 |

Scenes name an NPC 2–4× as often as the NPC sections do, and some sessions
mention an NPC with no entry for them at all (Ilvara: 4 of 10 sessions). An
entry is a one-paragraph snapshot of the NPC. The scenes hold the beats:
what they did, in what order, and what they said (moments preserve quotes
character for character). Approach 11 measured the same effect: resolving names
through the alias file raised one NPC's mentions from 4 to 15.

**A mention is not presence.** This is the narrator-eligibility lesson in
`CLAUDE.md`, where the GM narrates *about* an absent character. The linker
labels linked material `mentioned in scene NNN.SS`, never `present in`. The
render prompt must keep that distinction ("discussed by the party" vs "appears").

## Proposed shape

```
summary_native build             (exists)  → dossiers/npc_<slug>.md          deterministic
summary_native link    NEW       (no LLM)  → dossiers/npc_<slug>.linked.md   deterministic, byte-identical
summary_native dossier NEW       (LLM)     → npc_dossiers/drafts/<slug>.md   one call per selected NPC
                                             npc_dossiers/runs/<ts>/         prompt, input digest, selection
GM review → promote by hand → docs/npcs/<slug>.md
```

**Linker rules** (deterministic, testable against fixtures):
- Match forms: the dossier's own headings plus registry exact aliases of the
  same type. Case-sensitive, word-boundary. No fuzzy matching, no
  model-proposed aliases.
- **Ambiguous forms are reported, not linked.** If a form names more than one
  registry entity, or is a short common word (`Stool`, `Ront` are fine, but
  something like `Spider` is not), it goes in `link_report.md` for the GM to
  rule on in `canon.yaml`. This is the same pattern as the possible-duplicates
  listing.
- Emit, per chapter in order: the entry paragraph, then each linked scene (id,
  title, the full scene text or the bullets naming the NPC), then each linked
  moment. Carry `file:line` for every item.
- GM secret identities (the "alias file mixed surface equivalence with secret
  identity" finding in approach 11) are **not** registry aliases and must not
  link. A secret identity is a separate, GM-scoped input.

**Render template** (adapted from `planning_build_synthesize.md`, with the
fields the summaries cannot support removed or flagged):
- *Computed header, not generated:* canonical name, aliases, type, first seen,
  last seen, chapters list, entry/scene/moment counts.
- Identity; Personality & motivations (as demonstrated, with cited examples);
  History with the party (chronological, every bullet ends `[ch NNN / NNN.SS]`);
  Last observed state (quoted from the latest entry, labelled with its chapter);
  Relationships; Notable quotes (verbatim from moments only).
- **Dropped:** "what remains hidden from the party". Summaries are a record of
  play and do not hold GM secrets, so the model would invent them.
- **Arc score events:** candidates with quoted triggers only, never values (the
  existing rule).
- Unsupported claims are labelled, not narrated (approach 12's audit rule).

**Cost:** OOTA has 222 NPC dossiers. The median has 4 observations, p90 has 15,
and the largest has 81. Even with linked scenes, the largest fits in one call
without chunking. Selecting with `recurring_min` cuts the render set to a few
dozen NPCs. Re-renders are incremental: store each linked dossier's digest and
re-render only NPCs whose digest changed. This is the store-and-projection idea
(approach 9) applied where it fits naturally, since every NPC is its own section.

**Spark angle:** this is a good local-model calibration task. Each call has a
bounded context, the model only renders, the template is fixed, and every claim
carries a citation, so drift is mechanically checkable (every `[ch/scene]` tag
must exist; every quote must appear verbatim in the summaries). Running the same
evidence packs through Spark and Claude gives a clean A/B with an objective
check. Claude will win on prose; the interesting measurement is citation and
quote fidelity.

## Approaches considered and rejected

| # | Approach | Why not, for NPC dossiers |
|---|---|---|
| 1 | `planning --build-dossiers` (live today) | Re-extracts from the narrated bible (`TheUnderdark.md`), which undoes a rendering step (F10). The model decides which NPC each mention belongs to, so it makes the identity decision. Existing dossiers are never rewritten, so new evidence collects in `.new_notes.NNN.md` sidecars that only hand merges clear. It has invented NPCs before |
| 2 | Shared chapter extract | Killed. Planning dossiers fell from 17 to 5 ("the narrowness *is* the depth") |
| 3 | Hand curation / `/dossier-merge` | Kept only as a stopgap. Under this proposal a correction goes into the summary or `canon.yaml`, so it survives regeneration |
| 4, 8 | Ensemble atomic-fact dossiers (+ model work on them) | This is the exact failure case: atomisation inverted roles, the inverted fact became the antagonist's only fact, and synthesis turned it into "Current status: Alive". 98% single-sample facts, so agreement can't filter. Hours of runtime |
| 6, 7 | Two-stage / entity typing | Fixes for the fact substrate. Not needed when the substrate is already structured and typed by section |
| 9 | Projections | The design is right, but the inputs were wrong. Only its incremental re-render idea is adopted (above) |
| 10 | Knowledge graph / semantic search | The model-written graph merged a villain with his master and imported module canon as history (F7). zg search stays useful for GM lookups, not as a dossier source |
| 11 | Event-ordinal graph | **Adopted in part.** Its scene-ordinal linkage is the linker. Its separate graph store isn't needed, because summary-native already owns the parse |

## Open questions for the GM

1. Should promoted dossiers replace `docs/npcs/` wholesale, or live beside it
   (e.g. `docs/npcs_summary_native/`) until compared?
2. Linking unit: the whole scene text, or only the bullets/paragraphs naming the
   NPC? Bullets are tighter. Whole scenes keep "who else was there".
3. Do monsters filed under `## NPCs` (`npc_aquatic_troll`, `npc_animated_drow_statues`)
   get dossiers, or does selection exclude entries with few observations?
4. Where should GM-only secrets for an NPC live, if a dossier is to show them?
   A separate hand-authored file the render reads under a "GM secret"
   label is the safe shape.
