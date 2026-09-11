# Generating campaign state and world state for LLM prep

**Method** — knowledge graph + zvec-grep. Companion to [FINDINGS.md](FINDINGS.md),
which is the evidence this method rests on. Tracking issue:
[CampaignGenerator#463](https://github.com/kostadis/CampaignGenerator/issues/463).

The consumer is a **prep session** — a downstream LLM that treats these
documents as ground truth. That shapes every rule below: whatever the documents
contain, the prep session inherits, including errors and interpretation.

---

## 1. The approach in one paragraph

Build a knowledge graph from the session summaries **without any model**, keyed
on **event order** rather than calendar date. Take *time* from `## Scenes`,
*state* from `## NPCs / Locations / Items`, and *identity* from the GM's reviewed
alias file. Use `zg` alongside it for natural-language lookup and to verify
individual facts. Generate each state document by running a specific graph
query per section, and emit terse, cited lines — never prose.

## 2. Why this and not the alternatives

| Approach | Outcome on this corpus |
|---|---|
| cognee (LLM-built graph) | Invented facts at ingest — 1.18× the source in generated prose; false entity merges; module content stored as play history. Unfit as a source of truth for prep. |
| Semantic search alone (zg vector, mempalace) | Good lookup, but **cannot enumerate** (returns vivid passages, not all of them), **cannot report absence**, **cannot order by time**. |
| Date-keyed KG (mempalace) | Correct when every fact is dated. `NULLS LAST` sorting made an undated June session the "most recent". |
| **Event-ordinal KG + zg** | Deterministic, complete, correctly ordered, cited. Answers every time question the others failed. |

---

## 3. Build the knowledge graph

Reference implementation: `scripts/kg/event_kg.py` (SQLite, ~1 s).

### 3.1 Time axis — event ordinal

Every event gets one global integer, from three authored orderings:

```
session  ← filename prefix     001, 002, 003, 003a, 004 … 011
scene    ← position in ## Scenes
beat     ← position of the bullet within the scene
```

- Sort sessions by `(int(prefix[:3]), suffix)` so `003a` falls between `003` and
  `004`.
- **Never use dates for ordering.** Keep them as an attribute only (§8.4).
- A session with no `## Scenes` content gets **no** events and is recorded as
  unwritten, not skipped (`009-session-not-written.md`).

Tables: `sessions(sess, ord, title, date, written, first_ev, last_ev)`,
`events(ev, sess, scene_idx, title, summary)`, `beats(ev, beat_idx, text)`.

### 3.2 State — snapshots

Each `### Entry` under `## NPCs`, `## Locations`, `## Items` is that entity's
state **as of the last event of its session**.

`snapshots(entity, sess, as_of_ev, section, text)`

- Current state = the snapshot with the highest `as_of_ev`.
- State as of event *N* = highest `as_of_ev ≤ N`.
- **Snapshots lag** — see §8.1. Current state is latest snapshot **plus any
  later mentions**, never the snapshot alone.

### 3.3 Identity — mentions

`mentions(ev, entity)` — an entity is mentioned in an event if any of its
surface forms appears in the scene's title, summary, or beats.

- Surface forms come from the campaign's reviewed `aliases.json`. **This is the
  one precision decision in the design, and the GM makes it** — deciding which
  names refer to the same person is exactly where an LLM-built graph went wrong
  (it merged a villain with his master).
- **Snapshot keys must be resolved through the same alias map as mentions.**
  Otherwise heading drift splits one entity into several (§8.2).
- Match the longest surface form first; skip forms of two characters or fewer.

### 3.4 Validate the build

Before generating anything, check the counts against an independent extraction:

```
sessions 12 · events 72 · beats 936 · snapshots 253
```

These matched three separate methods in this work (`tgrep`, `zg --rg`, and a
standalone extractor). A mismatch means a section was mis-parsed — find it
before trusting any document built on top.

---

## 4. Index with zg

`zg` is the lookup layer, **not** the enumeration layer.

| Use `zg` for | Use the graph / `zg --rg` / `tgrep` for |
|---|---|
| "What happened to Droop?" — a question in plain language | Listing *all* completed events |
| Verifying one fact before it goes into a document | Every entity's latest state |
| Finding which entity a fact is filed under | Anything involving order or recency |

- Index only the summaries: `zg --index . -g '**/*.md'` from the summaries
  directory, and **confirm Coverage = 100%** in `zg --status`.
- `--preview full` whenever piping, or results arrive as headings with no body.
- The `/campaign-recall` skill (`skill/campaign-recall.SKILL.md`) wraps these
  rules.

---

## 5. Generate campaign_state

Answers: *what has the party finished, and what is on the table now?*

| Section | Source query | Deterministic? |
|---|---|---|
| **Completed encounters** | `events` in ordinal order, grouped by `sess` — scene title + `####` summary | yes |
| **Last N events** | `events ORDER BY ev DESC LIMIT N`, regrouped by session | yes |
| **NPC current states** | latest snapshot per entity **+** mentions after it | yes, given §3.3 |
| **Last seen** | `MAX(ev) FROM mentions WHERE entity=?` → "last seen event 38 of 72, 34 events ago" | yes |
| **Resolved plot threads** | identity revelations and answered questions | **no — GM** |
| **Active quests / open threads** | offers and promises not yet discharged | **no — GM**, with graph evidence |
| **Party current situation** | the final event of the highest-numbered written session | yes |

## 6. Generate world_state

Answers: *who and what exists, and how do things stand?*

| Section | Source query | Deterministic? |
|---|---|---|
| **Party roster** | latest `NPCs` snapshot for each PC and sidekick | yes |
| **Key NPCs** | latest snapshots, grouped | grouping is **GM** (ally / ambiguous / antagonist) |
| **Locations** | latest `Locations` snapshot per location | yes |
| **Notable items** | latest `Items` snapshot per item | yes |
| **Factions** | not a section in the summaries | **GM** |
| **Timeline** | `sessions` + `events`, ordinal order | yes |

**The split matters.** Everything marked *yes* is copied from reviewed text by a
query. Everything marked *GM* is a precision decision — scope, attribution, or
classification — and must not be delegated to a model that feeds the prep
session unreviewed.

---

## 7. Output rules for an LLM consumer

1. **Terse lines, not narration.** A prep session inherits interpretation along
   with facts. *"First time this party has run"* carries a reading;
   *"retreated from the barracks fight, event 54"* does not.
2. **Cite every fact** — `008-session-08-02.md:210`. Checkable in seconds, and
   the prep session can go to the source for texture instead of to a paraphrase.
3. **Quote, don't paraphrase.** Anything in quotation marks is verbatim.
   Paraphrase is where meaning drifts: *"not in a place where dead is easy"*
   became *"a dangerous location"* in an LLM-built graph.
4. **Make gaps explicit.** Name the unwritten session. Say "last recorded at
   event 38; nothing since." An unresolved thread left visibly unresolved is the
   correct output.
5. **Separate established from believed.** "The record shows" for events;
   "Sildar says" for claims.
6. **Separate party knowledge from GM knowledge** (§8.3).

---

## 8. Issues uncovered

Ordered by how badly each would corrupt a prep document.

### 8.1 Snapshots lag behind events

**13 of 38 NPCs** with both a snapshot and a mention have a latest snapshot
older than their latest mention. A character can be discussed without getting a
fresh `## NPCs` entry.

| Entity | Last snapshot | Last mentioned |
|---|---|---|
| Gundren Rockseeker | `003a` | `006` — *"the DM connects Iarno to responsibility for Gundren Rockseeker's capture"* |
| Iarno "Glasstaff" Albrek | `006` | `008` |
| Tuck | `004` | `008` |

**Fix:** current state = latest snapshot **plus** every mention after it. A state
document built from snapshots alone is stale for a third of the cast.

### 8.2 Heading drift splits entities

The same person gets different `### headings` across sessions:
`Pip` → `Pip Thistlewick`; `Sister Maela` → `Sister Maela Dawnforge`; the nothic
appears as `The Nothic`, `Nothic`, and `Ssarnak`. Keyed on raw headings, `Pip`'s
snapshots stop at session 001 while he is mentioned through 011 — **67 events**
of apparent lag that is really one character stored twice.

**Fix:** resolve snapshot keys through the alias map (§3.3). The reference
implementation currently does this for mentions only — **known bug**.

### 8.3 The alias file mixes two kinds of decision

| Kind | Example | Known to |
|---|---|---|
| Surface-form equivalence | `Gundren` = `Gundren Rockseeker` | everyone |
| Secret identity | `The Spider` = `Nezznar` = `the drow` | the GM only |

"Nezznar" appears in **zero** session summaries; it comes from planning and the
module inventory. Resolving through both kinds labels the party's antagonist with
a name they have never heard, and *"the drow"* spoils an unrevealed fact.

**Fix:** split the alias file. Surface forms drive mention matching. GM-only
identities are carried as annotations, never as canonical labels in
party-knowledge output.

### 8.4 An identity revelation is itself an event

The party learned Glasstaff was Iarno Albrek in session 005. `Glasstaff = Iarno`
is not simply true — it is true **from that event** for the party, and always
for the GM.

**Fix:** store `(Glasstaff, same_as, Iarno, from_event=30)`. Then *"what did the
party know as of event 25"* is answerable, and GM-only identities stay out of
party knowledge because no event ever reveals them.

### 8.5 Mention counts depend entirely on aliases

Gundren with canonical names only: **4** mentions. Through `aliases.json`:
**15**, across six sessions. Last-seen happened to be right either way — his
final mention used the full name — which is luck, not method. Always resolve
through aliases, and treat an entity with suspiciously few mentions as a likely
alias gap.

### 8.6 Dates are unreliable — use them as attributes only

- `003a`: *"Date: Not recorded in the Zoom summary"* — genuinely undated.
- `004`: *"Date: Jun 17th, 2026"* — dated, but not ISO. A strict parser drops it.
- Session 11: directory `011-20260904`, content `Date: 2026-09-05` — the source
  disagrees with itself by a day.

A date-keyed timeline sorted `NULLS LAST` promoted `003a` (June) to "most
recent". The ordinal cannot fail this way.

### 8.7 Play-order position is not a chapter number

`003a` takes an ordinal slot, so from `003a` onward the play-order position runs
one ahead of the chapter number. Reading one as the other put Gundren's last
mention in "Chapter 7" when it is Chapter ~6. Four sessions (`004`, `005`, `006`,
`008`) have no chapter number in their titles at all. **Carry session id, chapter,
and ordinal as three separate fields.**

### 8.8 Header levels are ambiguous

Scene titles and NPC entries are both `###`. A naive `^###` enumeration mixes
them. **Always scope by the enclosing `##` section** — `## Scenes` vs `## NPCs` —
before parsing `###` entries.

### 8.9 Monolithic sections defeat retrieval

One session's `## NPCs` section was a single 18,987-character chunk covering 13
NPCs. Its embedding represented all of them, so a query about one character
never ranked it — Droop's abandonment was invisible to retrieval. The graph is
unaffected (it parses structure, not embeddings), but **`zg` lookups over the
raw summaries are**. Split per entity before indexing for lookup. `## Spells` is
still unsplit.

### 8.10 Consequences live in prose bodies

The `####` scene summaries are one line each. A campaign state built only from
them is thinner on *consequences* than a hand-written one — "three bugbears
survive, wounded, and loose" lives in the scene body. For prep this terseness is
mostly a feature (§7.1), but outstanding obligations — who is owed what — should
be pulled from the bodies at full detail, because they drive session planning.

### 8.11 Indexes fail silently

Three tools reported success over work they had not done: cognee
`status='completed'` over a path ingested as text; tgrep `"complete": true` with
195 of 1,092 files unindexed; `zg --rg -l` rejected on stderr and read as "not
recorded". Also: `zg --rg` prints `No matches.` to **stdout**.

**Fix:** rebuild before each generation run, and run a **positive control** —
the same query against a name certainly present — before trusting any negative.

---

## 9. Validation checklist — every generation run

- [ ] Summaries index rebuilt; coverage 100%
- [ ] Graph counts match an independent extraction (§3.4)
- [ ] Positive control returns hits
- [ ] Unwritten sessions listed, not dropped
- [ ] Every entity's current state checked for later mentions (§8.1)
- [ ] No GM-only identity used as a canonical name (§8.3)
- [ ] Quoted strings verified verbatim — `scripts/retrieval/verify.py`
- [ ] Proper nouns verified present in the summaries — `verify.py`
- [ ] GM-classified sections (resolved threads, open quests, factions, ally /
      antagonist) reviewed by the GM before the prep session reads them

`verify.py` catches imported names and paraphrased quotes. It **cannot** catch
false relationships between real entities — that is what the GM review is for.

---

## 10. Open work

1. Resolve snapshot keys through the alias map (§8.2) — known bug.
2. Normalise quote characters (`"Glasstaff"` vs `'Glasstaff'`).
3. Split `aliases.json` into surface forms and GM-only identities (§8.3).
4. Record identity revelations as event-bounded facts (§8.4).
5. Emit `campaign_state` and `world_state` directly from graph queries — this
   work built the graph and separately built the documents via `zg`; the
   one-step generator is not yet written.
6. Pull outstanding obligations from scene bodies at full detail (§8.10).
7. Split `## Spells` for `zg` lookup (§8.9).
