# Event-ordinal knowledge graph for Phandalin campaign state

**Date**: 2026-09-19
**Predecessor**: `experiments/20260911-retrieval-time-kg/` — [FINDINGS](../../experiments/20260911-retrieval-time-kg/FINDINGS.md), [STATE_GENERATION_METHOD](../../experiments/20260911-retrieval-time-kg/STATE_GENERATION_METHOD.md), issue #463
**Measurement**: `experiments/20260919-phandalin-event-kg/`
**Status**: proposal — nothing built beyond the measurement pass

The predecessor established a method on Obelisk (12 sessions): build the state
graph from session summaries **deterministically**, keyed on event order rather
than date, and keep the model out of the fact path. This asks whether the method
survives Phandalin — 53 sessions, 20 MB, 4.4× the corpus — and what it would
replace.

Short answer: it survives, every hazard the predecessor catalogued is present
and several are worse, and the corpus has two failure modes the predecessor's
corpus did not exhibit.

---

## 1. The measurement pass

`experiments/20260919-phandalin-event-kg/phandalin_kg.py` — the predecessor's
`event_kg.py` retargeted at `Phandalin/docs/summaries`, run read-only. **0.8 s.**

```
sessions      53   (50 written; 001, 020, 023 are not-written stubs)
events       356
beats      5,255
snapshots    883
mentions   2,752
entities     987   (594 from entity_registry.yaml + 393 heading-only)
```

Three deliberate changes from the predecessor:

- identity resolves through `docs/entity_registry.yaml` (typed, GM-reviewed,
  carries `rejected_aliases`) rather than the flat `aliases.json` projection
- **snapshot keys resolve through the alias map** — `STATE_GENERATION_METHOD`
  §8.2, listed there as a known bug (§10 item 1). Fixed here.
- session id, chapter number, and ordinal are three separate fields (§8.7)

### Validation (§3.4)

Counts cross-checked against an independent `awk` extraction:

| | graph | awk | |
|---|---|---|---|
| scenes | 356 | 356 | ✓ |
| snapshot entries | 883 | 883 | ✓ |
| beats | 5,255 | 5,251 | Δ4 — indented sub-bullets the `^- ` pattern misses |

Positive control: `Valphine` returns 764 hits inside `## Scenes` sections, so
mention matching demonstrably works before any absence is reported.

---

## 2. Every catalogued hazard is present

| § | Obelisk (12 sessions) | Phandalin (53 sessions) |
|---|---|---|
| 8.6 dates | 2 formats, 1 undated | **3 incompatible formats** — 30 ISO, 13 `Apr 18th, 2026`, **7 in-world** (`03-02 of Taraskh 1495`), 3 missing |
| 8.7 chapter ≠ ordinal | `003a` offset by one | **collision** — 52 distinct chapter numbers for 53 sessions |
| 8.1 snapshot lag | 13 of 38 (34%) | 57 of 224 (25%) |
| 8.2 heading drift | `Pip` / `Pip Thistlewick` | 547 raw headings → 527 entities; 17 multi-headed |
| 8.8 header ambiguity | mixes scenes with NPCs | naive `^###` → **1,479** vs 356 real scenes |
| 8.9 monolithic sections | 18,987-char block | 13,422-char session state block (032) |

### 2.1 The date axis is unusable (§8.6)

Three formats, one of them a different calendar entirely. Sorting sessions by
the date string makes **session 041 of 53** the most recent. Two sessions share
the same in-world date. Directory names disagree with their own contents
(`20260318-035-session-2026-03-26`).

The ordinal cannot fail this way. This is the predecessor's central claim and
Phandalin proves it harder than Obelisk did.

### 2.2 `049` / `049a` (§8.7)

Both are titled `# Chapter 49: The Only Viable Shipper`. They are **different
real sessions** a week apart — 049 on 2026-08-11 (8 scenes, the Counting House
and Margaster Logistics), 049a on 2026-08-18 (5 scenes, the Spire of the
Morninglord).

049a is the direct continuation of 049. Three next-day promises set up in 049
are discharged in 049a:

| Set up in 049 | Discharged in 049a |
|---|---|
| Cullen will "share the information the following day" | "Cullen provided the name **Bimble Nackle**" |
| Aurelan will "make inquiries into House Margaster by the next day" | Aurelan reports on the Commission |
| Perrin must produce "three independent witnesses" | "He arrived with three witnesses" |

So the **ordinal is correct** and the spine is sound. Only the label is wrong:
049a inherited its predecessor's title and never got its own.

**Recommendation: do not renumber.** Carry session id, chapter, and ordinal as
three separate fields and the chapter number need not be unique. Renumbering
049a → 50 and shifting 050–052 is exactly the operation that produced the `+1`
drift recorded in `campaign_state.md`, which went unnoticed for weeks and had to
be verified against four independent scene points to correct. Retitling costs
nothing; renumbering risks a repeat.

### 2.3 Snapshot lag (§8.1)

57 of the 224 entities that have both a snapshot and a mention (25%) have a
latest snapshot older than their latest mention.

| Entity | Latest snapshot | Latest mention | Lag |
|---|---|---|---|
| Valphine | event 75 | event 356 | 281 |
| Aletra | event 209 | event 352 | 143 |
| Elmar Barthen | event 134 | event 314 | 180 |

Current state must be *latest snapshot plus every mention after it*. A document
built from snapshots alone is stale for a quarter of the cast.

The §8.2 fix demonstrably works: Harbin Wester's 15 snapshots arrive under three
headings (`Harbin Wester`, `Townmaster Harbin`, `Townmaster Harbin Wester`) and
now merge into one entity — his latest snapshot (event 317) is *newer* than his
latest mention (314), so he correctly does not appear as stale. Unresolved, he
would have split three ways and at least two fragments would have read stale.

---

## 3. Two failure modes the predecessor did not see

### 3.1 The corpus silently loses sessions

Reconciling the 54 raw session directories under `Phandalin/summaries/` against
the 53 normalized files in `docs/summaries/`:

- **`035a`** exists as a raw session with a real `session-summary.md`
  (10,429 B) and has no normalized file. **GM ruling 2026-09-19: ignore it.**
  Verified clean — nothing in `docs/` references `035a` and the chapter spine
  34 → 35 → 36 → 37 is contiguous without it.
- Raw ordinals **`008` and `027` each appear twice**, on different dates with
  different content (`20250805-008` holds "Chapter 07", `20250812-008` holds
  "Chapter 08"). Raw directory ordinals are not a key; only the `docs/summaries`
  prefixes are.
- `001` and `020` are normalized stubs with no raw directory.

Nothing currently checks any of this. A session can vanish between the raw
directory and the normalized corpus with no signal.

**A recorded-exclusion file is required**, not a silent skip — the value of the
check is catching the *next* gap, and "skip anything odd" erodes to nothing.
Following the `corrections.yaml` convention already in the repo (hand-authored,
reason attached, pruned only by a human):

```yaml
# Phandalin/docs/summaries_exclusions.yaml
version: 1
campaign: Phandalin
exclusions:
  - raw: 20260324-035a-session-2026-03-18
    ordinal: 035a
    reason: <GM to fill>
    decided_by: GM
    decided: 2026-09-19
```

Reconcile then fails on any raw session directory that is neither normalized nor
listed here.

### 3.2 Section-name drift drops state silently

The corpus has a stable five-section vocabulary (`Summary`, `Scenes`, `NPCs`,
`Locations`, `Items`, plus `Spells` and `Memorable Moments`) — except in four
places:

| File | Off-vocabulary heading |
|---|---|
| `011` | `## Player Characters` |
| `026`, `037` | `## Spells and Abilities` |
| `032` | `## Features` |

**23 `###` entries live under these.** A parser with a fixed section allowlist
drops them without complaint. This is how Valphine's session-011 roster entry
vanished from the first build of this graph — which is also why her measured lag
is 281 events. The validate stage must assert the H2 vocabulary and fail on an
unrecognised heading rather than skipping it.

---

## 4. Module content is stated as play history

**399 of 594 registry entities have zero mentions in any scene** (154 location,
117 npc, 36 faction, 36 event, 31 item, 16 deity, 9 concept).

Spot-checked against the raw corpus, not just the graph: `Gnerkli`, `Korboz`,
`Sister Garaele` and `Facktoré` occur **zero times anywhere in the 53 summary
files** — not in `## Scenes`, not in `## Summary`, nowhere. The positive control
passes in the same run, so this is absence, not a broken query.

Yet the production `Phandalin/docs/campaign_state.md` states:

> **Gnomengarde — King Gnerkli Freed / King Korboz Madness Resolved:** Mimic's
> death resolved the crisis. Both kings functional […]

> **Gnomengarde — Facktoré and Autoloading Crossbow (area G7):** Device
> disabled; Facktoré fled […]

alongside module area codes (`area E1`, `G7`, `G9`, `G10`) that match no pattern
in the summaries.

**This is not proof the pipeline invented anything** — `campaign_state.md` is
fed from `docs/chapters/` and a module inventory as well as the summaries, and
these facts may be perfectly true. The defect is that **the document does not
distinguish its sources**, and nothing in it marks which claims come from play.
A prep session reading it inherits module content as established history — the
same failure diagnosed with cognee in the predecessor work.

### The fix uses machinery that already exists

`registry.py add` already accepts `--provenance module|supplement|on_the_fly`.
The field is populated on **22 of 594 entities** (1 `module`, 11 `supplement`,
10 `on_the_fly`) — about 4%. Populating it is what lets a generated document
label every line `play` / `module` / `gm`. No new schema is needed.

---

## 5. Relationship to existing machinery

### 5.1 `pipelines/grounding/campaign_state.py` — what this replaces

Two LLM passes: chunk-and-extract, then synthesize. That is
LLM-extracts → LLM-structures → LLM-renders, the pattern the repo's own pipeline
rule names as the bad one: *"Errors compound silently."*

The graph removes the **structure** decision from the model entirely. The model
keeps a real role — rendering GM-approved structure into prose, and drafting the
GM worksheet — but never feeds itself.

It also dissolves a standing operational problem. `campaign_state.md` carries
three separate `HAND-EDITED — re-running the pipeline will discard these edits`
warnings. When regeneration is deterministic and costs a second, hand edits move
into the *inputs* (aliases, exclusions, the GM worksheet) instead of being
stranded in the output.

### 5.2 `entity-triage` skill — what this does **not** replace

The skill owns **identity**: who is who, what counts as an entity, alias vs
distinct. That is a precision decision, GM-ruled one candidate at a time, and
nothing here should touch it.

The graph owns **time and state**, and *consumes* the registry the skill
maintains. Clean separation; no overlap.

There is one thing the graph can offer triage. The queue's candidate corpus is:

```
.triage_queue.json  generated_from:
  docs/ensemble/per_chapter/*/merged.json
  docs/ensemble/merged.json

docs/ensemble/per_chapter/  →  chapter_01 … chapter_07   (7 of 52)
merged.json (3,014 facts)   →  Cullen: 0  Bimble: 0  Aletra: 0
                               Margaster: 0  Axeholm: 0
```

**The ensemble covers chapters 1–7.** The play record runs to 52. So 45 chapters
of proper nouns are structurally invisible to `triage-candidates` — which is why
`Perrin Alagondar`, `Brother Aldric` and `Rift Weavers` are absent from the
registry *and* from the queue *and* from the `ignored` list. They were never
candidates. The live plot's cast sits outside the queue's reach.

> **Correction (2026-09-19, after this landed).** An earlier draft listed
> `Aletra` in that set. It is wrong: `Aletra Sotorra` **is** registered, and
> `Registry.known_names()` applies a multi-word first-token expansion, so bare
> `Aletra` resolves as known. The original check here matched names and aliases
> literally and missed that expansion. The three names above were re-verified
> through `known_names()` itself. The coverage finding is unaffected and is in
> fact stronger than stated — see the measured figure below.

Consequence worth stating plainly: **running `/entity-triage` today would triage
the wrong 172 names.** The skill's Phase 0 says regenerate the queue first, but
regenerating is not enough here — the corpus behind it stops at chapter 7.

The graph reads `docs/summaries` directly and therefore sees all 52 chapters.
Its 393 heading-only entities are `###` headings the GM already wrote under
`## NPCs` / `## Locations` / `## Items` — a *higher-precision* signal than a
proper-noun sweep, because an authored heading is an assertion that something is
an entity. Offered as a **second candidate source** covering the 45 chapters the
ensemble does not reach, feeding the existing triage flow. Not a parallel one.

**Measured.** `experiments/20260919-phandalin-event-kg/triage_from_summaries.py`
emits a `.triage_queue.json` from `docs/summaries` alone, reusing the real
`norm_subject`, `known_names`, near-miss and GM-suppression paths so only the
*corpus* differs. Against the same registry:

| | candidates |
|---|---|
| Existing ensemble queue (chapters 1–7) | 148 distinct |
| Summaries queue (all 52 chapters) | **1,074** — 357 heading, 13 both, 704 mention-only |
| In the summaries queue only | 1,003 |
| **Heading/both candidates sourced from chapters 8+** | **326 of 370** |

A worked example: `Bimble Nackle` is registered, and first-token expansion
covers bare `Bimble` — but the party's nickname `Bimbo` is not aliased to him
and surfaces as a live candidate (5 occurrences, sessions `050` and `052`),
right across the currently-active plot thread. An ordinary alias ruling the
skill handles well; it simply never reached the queue.

---

## 6. The proposed prototype

Four stages, all deterministic, no model in the fact path.

```
1. build       docs/summaries → SQLite                    [working, 0.8 s]
2. reconcile   raw dirs vs normalized files vs exclusions [fails loudly on a gap]
3. validate    counts vs independent extraction
               H2 vocabulary assertion
               positive control
4. emit        one SQL query per section, every line cited file:line
               + a GM worksheet for what a query cannot decide
```

### Section determinism

| Section | Source | Deterministic? |
|---|---|---|
| Completed encounters | `events` in ordinal order, grouped by session | **yes** — 356 rows |
| Last N events | `events ORDER BY ev DESC LIMIT N` | **yes** |
| NPC current states | latest snapshot **+** mentions after it | **yes**, given alias resolution |
| Last seen | `MAX(ev) FROM mentions WHERE entity=?` | **yes** |
| Party current situation | final event of the highest written session | **yes** |
| Timeline | `sessions` + `events`, ordinal order | **yes** |
| Resolved plot threads | — | **GM** |
| Active quests / open threads | — | **GM**, with graph evidence attached |
| Faction / ally / antagonist grouping | — | **GM** |

Everything marked *yes* is copied from GM-authored text by a query. Everything
marked *GM* is a scope, ordering, or attribution decision and is emitted as a
**worksheet with evidence**, never auto-filled.

### Provenance on every line

Each emitted line carries a source class — `play` (from `docs/summaries`),
`module` (from the module inventory), `gm` (from planning). The 399-zero-mention
set seeds the `module` class. Without this the document keeps asserting Gnerkli.

### Scope of a first cut

Stages 1–3 plus the six deterministic sections. Roughly 300 lines; stage 1 is
already running. The GM sections stay a worksheet.

---

## 7. Validation checklist (every generation run)

- [ ] `reconcile` clean — every raw session either normalized or in `summaries_exclusions.yaml`
- [ ] Graph counts match an independent extraction
- [ ] H2 vocabulary assertion passes — no unrecognised section silently skipped
- [ ] Positive control returns hits before any absence is reported
- [ ] Unwritten sessions listed, not dropped (`001`, `020`, `023`)
- [ ] Every entity's current state checked for mentions after its latest snapshot
- [ ] No GM-only identity used as a canonical name in party-knowledge output
- [ ] Quoted strings verified verbatim
- [ ] GM-classified sections reviewed before a prep session reads them

---

## 8. Open decisions (GM)

1. **`049a` title** — it needs its own; the chapter number can stay 49 under the
   three-field design. Proper noun, so the GM picks it.
2. **`provenance` backfill** — 399 zero-mention entities are the candidate set.
   Which are *module imports* and which are *unrevealed but real* is a GM call.
3. **The ensemble's chapter 8–52 gap** — out of scope for this proposal, but
   everything downstream of `merged.json` is working from a seventh of the
   campaign.
4. **Build order** — stages 1–3 first, or the emit stage against the graph as it
   stands.

---

## 9. Reproducing the numbers

```bash
python3 experiments/20260919-phandalin-event-kg/phandalin_kg.py
python3 experiments/20260919-phandalin-event-kg/diag.py
```

Read-only against `~/phandalin`. Writes a SQLite file next to the scripts.
Environment: `zg` index over `Phandalin/docs/summaries`, coverage 100%, 53/53
files, 2,232 entities, `local/potion-code-16m-v2`, 256 dimensions.
