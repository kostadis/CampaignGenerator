# Ensemble Grounding — Investigation, 2026-07-27/28

## Why this doc exists

A field report said the OOTA grounding docs were stamped "Chapter 62" but
contained only Chapter 61 content. Chasing that produced four defects, three
merged PRs, and — more usefully — one recurring pattern that explains all of
them.

This is the pick-up-later record: what was found, what shipped, what is still
open, and which questions are yours to answer rather than mine.

---

## The through-line

**The pipeline computes a signal, serialises it, and then ignores it — forcing a
later stage to guess what it was already told.**

Four independent instances, found in order:

| # | computed | discarded | consequence |
|---|---|---|---|
| #194 | `chapters: lo-hi` per dossier | never read by synthesis | ranked by fact *frequency* instead → deleted the newest chapter |
| #197 | merge method (`subject` vs `embed`) | printed, never recorded; unreachable from the UI | 62 chapters silently merged with the weaker algorithm |
| #200 | quote position (`q in chunk` finds it) | kept only the boolean | within-chapter event order unavailable |
| #201 | which entities a fact mentions | never counted | hearsay-only dossiers indistinguishable from well-attested ones |

The second-order version, which is what #202 exists to address:

**Atomization strips the syntax that carries attribution.** The five extraction
lenses emit decontextualized facts — that is the point, it is what makes them
dedupable and countable. It is also why a sentence like

> Then he saw **what was lying next to him** and went still.
> "Moziqodo," he said. "Sylvira Savikas's son."

is unambiguous in its paragraph and unrecoverable as a fragment. No amount of
downstream clustering, voting, or embedding gets it back, because the information
was never in the fragments — it was in the sentence structure they were cut out
of.

---

## What shipped

### #194 → PR #196 — the dossier floor deleted the present

`synthesise_world_state.load_dossiers` filtered on `n_facts` and sorted
densest-first. An entity introduced in the newest chapter necessarily has the
*fewest* facts, so any frequency floor preferentially discards exactly the
material a "current state" document exists to report.

`10` was the **shipped schema default** (`EnsembleTuning.dossier_min_facts`), not
an operator choice, and `/ensemble/setup` had no tuning control at all — so the
value was reachable only by hand-editing YAML.

**Fixed:** recency scopes the floor. `--recent-window N` keeps everything touched
in the last N chapters whatever its count; `--background-min-facts` (renamed)
governs only what came before. Payload split into `RECENT` / `BACKGROUND`
segments with the prompt told which is the present. The run prints the window,
counts, and every recent entity by name — silent loss became visible loss. Both
knobs settable on `/ensemble/setup`. Old configs migrate on read with value
preserved.

Measured on OOTA (456 dossiers, latest chapter 62):

| window | recent | background (n≥10) | payload |
|---|---|---|---|
| — (before) | — | 88 | 88 |
| 4 (shipped default) | 64 | 62 | 126 |

All 7 Chapter-62 entities restored, including two single-fact ones the old floor
guaranteed to delete.

### #197 → PR #198 — the embed merge was unreachable, the downgrade illegible

`ensemble_merge` picks between two structurally different algorithms. `subject`
groups on `(type, normalized_subject)`, so facts filed under different subjects
are **never compared**. `embed` partitions on `type` alone and clusters on
embedding cosine.

`/run/extract` emitted no merge flags and `EnsembleConfig` had no field for any,
so a UI-driven extraction could not select `embed`. The whole 62-chapter corpus
was built with `subject`.

It was not literally silent — the method was printed — but the line read as a
plain statement of configuration, with nothing marking it as a fallback from an
unavailable better option, repeated 62 times interleaved across parallel workers.

**Root cause of the OOTA case, most likely:** the documented endpoint had been
dead for a month. The runbook said `--embed-endpoint http://spark2:8000
--embed-model Qwen/Qwen3-Embedding-0.6B`; that sidecar was replaced on
**2026-06-30** by Ollama on `:11434` serving `qwen3-embedding:0.6b`. Following
the documented procedure produced the silent fallback.

**Fixed:** the implicit fallback warns and names the three ways to enable
`embed`; the method line becomes `… [fallback — no embed endpoint]`. An explicit
`--method subject` stays quiet (nagging decisions is how warnings get ignored).
New `merge` config group, forwarded by `/run/extract`, endpoint settable on
`/ensemble/setup`. `ensemble_batch` also gained `--similarity`, which
`ensemble.py` accepted and that one hop was dropping.

### #200 — quote offsets (the within-chapter sequence)

`verify_quotes` did `q in chunk` — a boolean. `chunk.find(q)` costs the same and
returns the position.

**Fixed:** `ensemble_merge` stamps `quote_offset` against the source document
named in the manifest. `facts_to_state` orders bundles by
`(chapter, quote_offset)`.

Done at **merge** time, not extract time, deliberately: re-merging an existing
corpus takes seconds (the per-lens JSON is on disk), re-extracting is hours of
local GPU. Unlocatable quotes get `None`, not `0`, and sort **last** within their
chapter — an unfindable quote is usually fabricated or `...`-stitched, so leading
with them would be backwards.

Measured on ch62: **272/362 located**, tracking the 273 `quote_verified`. The one
gap is a chunker-injected `[Continuing — Speaker: …, Scene: …]` header, correctly
`None`.

---

## The case that drove it: Moziqodo (#195, OPEN)

In OOTA ch62 Moziqodo **is** the pit fiend and the party kills him. The extract
produced three facts from one quote and got the role right twice, wrong once:

| n_samples | lenses | subject | verdict |
|---|---|---|---|
| **3** | interiority, large, sweep | `Tadric` | identifies **the dead fiend** as Moziqodo ✅ |
| 1 | sweep | `Sylvira Savikas` | mother of Moziqodo, **the dead pit fiend** ✅ |
| 1 | **small** | `Moziqodo` | son of Sylvira and **the target of the pit fiend's attack** ❌ |

Because `facts_to_state` bundles by subject, the two correct readings landed under
other entities and the inverted one is the **only** fact in `npc_moziqodo.md`.
The dossier then amplified it: the fact never said he lived, the dossier says
*"Current status: Alive"* and *"Survived a pit fiend attack."*

### Hypotheses tested and killed

Worth recording so they are not re-tried:

- **Agreement as a filter.** Dead. **98% of corpus facts are `n_samples: 1`**
  (15,220 of 15,465) — the lenses extract different material by design, so "solo"
  is normal, not a red flag.
- **Embed-merge rescues it.** Dead, tested against the live endpoint. Re-merging
  ch62 with `embed` collapsed 362 → 346 facts but every `subjects[]` came back a
  **singleton**. The four facts are not paraphrases: correct-vs-inverted measures
  cosine **0.8465**. Embedding finds paraphrase, not contradiction — two
  statements disagreeing about who died are far apart by construction.
- **A contradiction detector.** Impractical. "Same quote, multiple subjects,
  mixed corroboration, ≥3 anchor" yields **15 candidate groups across 62
  chapters, of which 14 are benign** (the same event filed under both actor and
  ability: `Daz` / `Daz's Fireball` / `Fireball`). 1-in-15 precision, and
  separating the real one needs semantic judgment — another LLM call on
  unreviewed LLM output.

### What #200 did for it

Ordered by offset, the sequence refutes the fact on its own:

```
@20703  The pit fiend was killed by Thorin's two clean strikes.
@21377  Tadric regained consciousness and grabbed for the key…
@21513  Tadric identifies the dead fiend as Moziqodo          (n=3)
@21514  Moziqodo is … the target of the pit fiend's attack     ← 800 chars later
```

That makes the error legible. It does not correct it, and the dossier on disk is
still wrong — which is why **#195 stays open**. The remedies live in #201
(flag the dossier as hearsay-only) and #202 (state attribution rather than
re-derive it); neither has landed.

---

## Open issues

Four: **#195** (the attribution defect itself, described above), plus the three
below. #201 and #202 are the two candidate remedies for #195; #199 overlaps
#202 and they compose.

### #199 — `session-summary.md` already holds what the pipeline re-derives

`enhance_summary` produces a **structured** document: `## Summary / Memorable
Moments / Scenes` (ordered) `/ Locations / NPCs / Items / Spells`. Its
`## NPCs → ### Moziqodo` entry is a complete, correct per-entity dossier —
"a massive and powerful **pit fiend** … **the party stunned and slew him**" —
getting right every element the reconstruction got wrong.

And `chapter_62`'s six sections **are** that summary's scenes 3–8, in order, with
a POV name prefixed. So the shape is *structure → render to prose → re-extract
structure from the prose*, and the round trip is lossy in exactly the dimension
the five lenses then spend tokens guessing at. `chapters_glob` is the ensemble's
only input; `summaries/` is wired into nothing.

**Constraint:** 16 `session-summary.md` files for 62 chapters, only **11** with
the structured sections. It is a grounding authority where it exists, not a
replacement pipeline.

**Prerequisite nobody has done:** there is no chapter ↔ summary mapping.
Summaries are keyed by session date (`summaries/20260720/`), chapters by index,
and the internal headers disagree with both (`chapter_62_*.md` says
*"# Chapter 59"* — the known BOM off-by-one; three counters disagree).

### #201 — report entities attested only through other entities' facts

Reframed mid-discussion from *mention-based bundling* (a mitigation) to a
**coverage report**. The condition is **absence, not error**: Moziqodo's dossier
is thin because he is a referred-to entity, and referred-to entities exist in the
record only as a byproduct of other people's facts. The system should flag that,
not correct it — what happened stays a GM decision.

- A raw own-vs-mentioned ratio **does not work**: the top is `Madness`
  (0 own / 259 mentions), `the Abyss`, `the Material Plane` — concepts, which are
  *supposed* to be referred to. Moziqodo ranked 62 of 81.
- **Type-scoped to `npc`/`monster` it works**: 30 entities campaign-wide.
- **Purest case — Khaem: 0 own facts, 18 mentions, no dossier exists.**
  `facts_to_state` bundles by subject, so an entity that is never a subject
  produces no file at all.
- **Intersected with #194's window**, five dossiers to check before the next
  regeneration: Moziqodo (ch62), Nibbles (ch60), Brother Harren (ch60), Brother
  Quellin (ch60), Whistler (ch59).

**Where it goes:** `facts_to_state --list`, not `registry check` and not a new
CLI. `cmd_check` takes only `campaign_dir` and never reads `merged.json`; folding
coverage in would make a cheap always-runnable command depend on a corpus that
may not exist. `facts_to_state` is the only thing already holding **both** inputs
(corpus to bundle, registry for aliases), and `--list` is already documented as
*"the human checkpoint on what will be aggregated"*.

**The asymmetry that matters:** the two report sections cannot share a mechanism.
Thin-but-present entities come from iterating bundles; zero-fact entities have no
bundle and require iterating the registry. *The current design can only report on
entities it already decided to write a dossier for — and the ones it silently
declined to create are exactly the ones needing the flag.*

### #202 — a narrative pass that states what happened

Every fix above re-derives, by inference over fragments, what a plain statement
of events would carry natively. Nothing precludes producing that statement.

**Not a sixth lens.** All five `PASSES` run `extract_facts --agent X` and emit
fact-JSON validated against a fixed `ALLOWED_TYPES`. A narrative emits prose;
forcing it into that schema (a `scene` type) would re-atomize it and defeat the
purpose. So: a sibling artifact per chapter, alongside `merged.json`.

**Its virtues are fewer lossy hops and reviewability — not correctness.** A GM
can read 62 short narratives; nobody reads 15,465 facts. It is still LLM output
and needs a checkpoint before feeding synthesis.

**Chunking — resolved in discussion.** Make the chunk a *scene*. The mechanism
already exists: `prepare_chunks(split_chapters=…)` splits on a heading prefix
*"instead of by character count"*. Note that `annotate_pov` exists to re-inject
speaker/scene context into chunks that don't open with a heading — it is a
**repair for damage size-chunking inflicts**, and becomes unnecessary when
chunking structurally.

Scene sizes cooperate: **145 scenes**, median **3** per chapter, median
**5,250 chars** (smaller than today's 6,000 `small` chunk); only **5 of 145**
exceed 15,000, none exceed 25,000.

Heading conventions are **not** uniform, though:

| style | chapters | what `##` marks |
|---|---|---|
| `## Name — Scene` | 14 | scenes — directly chunkable |
| `## <date>` plain | 25 | date boundaries |
| `### Name` only | 7 | POV turns |
| none | 16 | nothing to split on |

So "chunk = scene" holds for 14; the generalization is *chunk on the best
available structural boundary* — 46 of 62 have one that is document-ordered, and
only 16 need the character-count fallback. `annotate_chunks_with_pov` already
detects all three conventions (`_H2_SPEAKER_RE`, `_H2_RE`, `_H3_RE`); reuse it.

**Second-order benefit:** structural chunks make the chunk index a *scene index*,
so every fact inherits which scene it came from. Complementary to #200 — offsets
give position, scene indices give grouping — and it is the natural join key
against #199's `## Scenes`.

---

## Loose ends and decisions that are yours

1. **The OOTA ch62 Moziqodo dossier is still wrong on disk**, and #194's recency
   window now *admits* it into the world_state payload (the old floor was hiding
   it by accident). Either hand-correct that dossier before the next
   regeneration, or accept a dead antagonist reported as alive.
2. **`--embed-threshold 0.93` is not calibrated for the model now serving.** It
   was measured on `nomic-embed-text-v1.5` (duplicates ~0.97, distinct ~0.78).
   Spot-measured on `qwen3-embedding:0.6b`: a true near-duplicate scores
   **0.9103** — *below* the threshold, so it would not merge. Three samples is
   not a calibration; the default was deliberately left alone. Needs a sweep
   against whichever model is live, and the answer moves whenever the sidecar
   does.
3. **Re-merging the OOTA corpus** would add quote offsets to all 62 chapters for
   free (per-lens JSON is on disk, no re-extraction). Worth pairing with (2) so
   it is done once, not twice.
4. **Should a zero-own-fact entity like Khaem get a stub dossier?** Strongest
   signal of absence, but writing a dossier with no first-hand facts arguably
   manufactures a record. My inclination is no — report it, don't create it — but
   it is a GM-facing call.
5. **A `CLAUDE.md` improvement was swept into the #194 commit** by a `git add -A`
   and is on `main` under a message that does not mention it. Content is accurate
   (the per-service config table and the "never add a default literal to
   `routers/ensemble.py`" rule); only the attribution is wrong. Split it out or
   leave it.

---

## Reference — measurements worth not re-deriving

Corpus: 15,465 facts, 62 chapters, 456 dossiers, 1,013 registry entities.

- `n_samples == 1`: **98%** (15,220). Agreement is not a filter.
- Cosine on `qwen3-embedding:0.6b`: near-duplicate **0.9103**, related-but-
  distinct **0.8465**, unrelated **0.3392**.
- Registry entities appearing anywhere in the corpus: **352 of 1,013**.
- Hearsay `npc`/`monster` (≥3 mentions, ≤2 own): **30**.
- Mention-based enrichment cost, if ever revisited: **+110%** blanket,
  **+14%** scoped to entities with ≤3 own facts.
- Scenes: **145**, median 5,250 chars, 5 over 15,000.
- Session summaries: **16** of 62 chapters, **11** structured.
