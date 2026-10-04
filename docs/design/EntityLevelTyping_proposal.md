# Entity-level typing: one type per subject, decided once

> **Status:** proposal, not built. Written 2026-10-03 from measurements against the
> Out-of-the-Abyss ensemble corpus (`docs/ensemble/per_chapter*/`) and the GM's
> type-merge rulings (`docs/ensemble/.type_merge_decisions.json`), at `511752c`.
> **Replayed** 2026-10-04 on the `monster` slice (§6.1); the replay found two fixes,
> now folded in: kept-separate is per file (§3, §5) and the queue holds named
> subjects only (§2). §8 names the general flaw this is one instance of: the
> pipeline asks the LLM for precision decisions and never reads the GM's rulings back.
> **Scope:** `pipelines/ensemble/facts_to_state.py` bundling only. Extraction
> (`extract_facts.py`, `ensemble_extract.py`) and `ensemble_merge.py` are unchanged.
> **Evidence and scripts:** `~/src/dgx-fun/vtt-spell-pass-local-design.md`
> ("Related negative result") and `~/src/dgx-fun/clef/ensemble-typing-eval/`.
> **Related:** `/ensemble-type-merge` skill (the manual cleanup this replaces);
> [NameResolution_proposal.md](NameResolution_proposal.md) (canon chain).

## 1. The problem

Every extracted fact carries its own `type`, chosen independently by whichever
lens and chunk produced it. `load_bundles` keys dossiers on **(type, canonical
subject)**. So an entity that one fact calls `npc` and another calls `monster`
becomes two dossiers — `npc_glabbagool.md`, `monster_glabbagool.md`,
`object_glabbagool.md` — and the GM merges them by hand. In OOTA that has happened
**109 times** (115 groups ruled, 9 kept separate).

The cause is structural, not a weak model. Per-fact typing gives a long-lived entity
dozens of independent chances to draw one odd label, and one odd label is a split.
Measured on OOTA:

| Who types each fact | Split entities among the 92 the GM merged | New splits among 55 entities that were fine |
|---|---|---|
| extraction (qwen, today) | 78 | 0 (by selection) |
| re-type every fact with Clef 27B | 29 | 7 — and moves 21 % of facts to event/thread/date |
| re-type with clef-flash / fast qwen | 46 / 38 | 13 / 13 |

Corpus-wide, re-typing creates roughly as many splits as it fixes. A better
per-fact classifier lowers the per-fact error rate but cannot make it zero, and
over dozens of facts per entity some split is close to certain.

## 2. The proposal

Decide the **entity** type once per canonical subject, then stamp it on every
entity-typed fact about that subject before bundling. A split becomes impossible by
construction.

Only the five **entity** types are resolved: `npc`, `monster`, `faction`,
`location`, `object`. Facts typed `event`, `thread` or `date` describe *what kind of
fact* they are, not what the subject is, and are left alone — re-typing them is what
drained 21 % of facts out of the dossiers in the Clef test.

### Resolution chain (first hit wins)

| Tier | Source | Authority |
|---|---|---|
| 1 | `docs/ensemble/type_conventions.yaml` (new, GM-written) | explicit per-subject or per-class filing rules |
| 2 | `.type_merge_decisions.json` → `primary` of a `merged` resolution | prior GM ruling |
| 3 | `entity_registry.yaml` `type`, through a GM-approved mapping (§4) | GM-curated canon |
| 4 | majority of the subject's own entity-typed facts, if the top type holds **≥ 60 %** | deterministic |
| 5 | none of the above → subject keeps per-fact types for now; **review queue** if it is a named subject | GM |

The queue holds **named subjects only** — those in `known_names` (registry names and
aliases plus party names). A generic creature that misses tier 4 ("galeb duhr",
"drow guards") is location-scoped anyway and would only bury the real questions:
in the replay, 20 of the 20 tier-5 subjects left after tier 2 were generic.

No model call in the chain. Tier 4's threshold is the one point the OOTA replay
tuned (vote-if-≥60 %-else-tiebreak scored 87/92 against GM primaries, versus 82/92
for the vote alone), and a model tie-breaker for tier-5 subjects scored the same
whichever model it was (Clef 27B, clef-flash, fast qwen) — so the queue goes to the
GM, not to a model. Adding an optional `--type-tiebreak <model>` later is cheap if
the queue proves long.

### Optional: a second opinion that flags, never decides

A model can serve as a **reviewer** of tier 4, not as a voter. For each subject the
vote decided, ask a model "what kind of entity is this?" from a sample of its facts;
if it disagrees with the vote, the subject keeps the vote's type **and** goes to the
review queue. Measured on the 92 OOTA groups (the vote alone was wrong on 10):

| Second opinion | Subjects flagged | Vote errors caught | False alarms | Cost |
|---|---|---|---|---|
| Clef 27B (any disagreement; ≥ 0.5 confidence is identical) | 15 | 8 / 10 | 7 | ~0.6 s / subject |
| fast qwen | 17 | 8 / 10 | 9 | ~2.7 s / subject |
| clef-flash | 18 | 8 / 10 | 10 | ~0.2 s / subject |

A queue of ~16 % of subjects that holds 80 % of the vote's mistakes is worth having.
Clef 27B is marginally the cleanest, but any of the three works — so the flag is
`--type-second-opinion <endpoint>`, off by default, and not a reason to dedicate a
Spark to Clef.

Rejected uses of a model **as a voter**, same data: a vote over Clef's per-fact types
scored 81/92; pooling Clef's per-fact types with extraction's scored 82/92; extraction's
own types alone scored 84/92 on that fact set. Extra votes add correlated noise, not
signal.

### Every resolution is reported

`facts_to_state` writes `type_resolution.md` beside the dossiers: one row per subject
— resolved type, the tier that decided it, the vote shares, and every conflict
between tiers. Tier-5 subjects and tier conflicts head the file. This is the GM's
review surface, and it replaces running `/ensemble-type-merge` after the fact.

## 3. Where it goes in the code

`load_bundles` already makes a whole-corpus pre-pass (`_collect_monster_vocab`).
Add a second one beside it:

```python
ENTITY_TYPES = {"npc", "monster", "faction", "location", "object"}

def resolve_entity_types(corpus_paths, aliases, conventions, merge_rulings,
                         registry_types, threshold=0.6) -> dict[str, Resolution]:
    """{normalised canonical subject: Resolution(type, tier, shares, conflicts)}"""
```

and in the bundling loop, one change before the key is built:

```python
t = f.get("type", "")
if t in ENTITY_TYPES and (t, slugify(display)) not in kept_separate_files:
    r = resolved.get(norm)
    if r is not None and r.type is not None:
        t = r.type
```

`kept_separate_files` is the set of `(type, slug)` **files** named in `kept_separate`
resolutions — not their subjects. A group can carry both statuses: Myconid Sovereigns
is ruled "merge `npc` + `monster` under `npc`, keep `faction` separate". Exempting the
whole subject would undo the merge half; exempting the file reproduces the ruling
exactly.

Everything downstream — `gkey`, `Bundle(t, norm)`, the dossier filename — then sees
one type per subject. The `is_known` / `monster_vocab` logic is unchanged, but note
the interaction in §5.

## 4. Decisions only the GM can make (blocking)

None of these is settled by this proposal; each needs an explicit GM ruling before
tier 3 or tier 1 can be written.

1. **Two existing GM rulings conflict.** Three separate questions:
   - *Demon lords.* The registry types Zuggtmoy, Juiblex and Demogorgon as `npc`;
     the type-merge primaries filed them `monster`. Yeenoghu is `npc` in both.
     Which one is the filing rule for demon lords?
   - *Yestabrod* (registry: Zuggtmoy's larval servant, leader of the Circle of
     Masters — not a demon lord) is `npc` in the registry, `monster` as a primary.
     Does it follow the demon-lord rule, or rule on its own?
   - *Ogrémoch* (registry: Prince of Evil Earth — an elemental prince, not a demon
     lord) is `deity` in the registry, `monster` as a primary. This one is really
     part of the `deity` mapping question in item 2.
2. **The registry's type list is not the dossier type list.** Registry:
   `npc, location, faction, item, deity, event, concept`. Dossiers:
   `npc, monster, faction, location, object`. Proposed mapping, for approval:
   `item → object`, `npc → npc`, `location → location`, `faction → faction`.
   Undecided: `deity` (Lolth, Tiamat, Bahamut, Entémoch, Blibdoolpoolp,
   Leemooggoogoon — the primaries filed these `npc`), `event` and `concept`
   (probably "not a dossier subject"), and whether anything maps to `monster` —
   the registry has no such type.
3. **Organisations that are also places.** Temple of Oghma: registry `location`,
   primary `faction`. Deepking Tarngardt: registry `npc`, primary `faction`. Myconid
   Sovereigns: registry `faction`, primary `npc`.
4. **Faerzress:** registry `item`, primary `location`.

Of the 92 OOTA groups, the registry covers 85 and agrees with the GM's primary on 69;
the 16 disagreements are exactly the four questions above.

## 5. Risks

- **Kept-separate rulings must stay separate.** Of the 9, several are not type
  problems but *mis-subjected facts* — `faction_daz.md` holds a fact about Daz's
  unknown Menzoberranzan patron, filed under Daz's name. Entity-level typing would
  re-type that fact `npc` and fold it into Daz's dossier, reversing a GM ruling
  (2026-07-26). Honour `kept_separate` rulings **per file**: facts whose original
  `(type, subject)` is a kept-separate member keep that type, while the subject's
  other facts resolve normally (§3). List them in `type_resolution.md` as "needs
  re-subjecting upstream". The real fix is in extraction, out of scope here.
- **Subject identity comes only from registry aliases.** Typing can only merge
  facts that already share a canonical subject, and `load_bundles` canonicalises
  through `entity_registry.yaml` alone — not the spell-pass glossary. A misspelling
  the glossary knows but the registry does not becomes its own subject. The replay
  found 18 such subjects across both corpora (e.g. `Zuggtomy`, `Grey Ghosts`,
  `Hightower Library`). Some come from extractions that predate a bible fix — ch31's
  `per_chapter` extraction (2026-07-13) still says "Zuggtomy", though the bible was
  corrected on 2026-07-18 — others from misspellings still in the bible. Either way
  this is a prerequisite, not part of this change: fix the source and re-extract, or
  add the variant as a registry alias (a GM-approved name change).
- **Generic creatures.** `monster_vocab` decides known-vs-anonymous by whether a
  subject ever appears as `monster`. If tier 1–4 resolves "the ghoul" to `npc`,
  anonymous location-scoping must still apply. Keep `monster_vocab` computed from
  the *original* per-fact types.
- **Same name, different entities.** Two real entities sharing one canonical subject
  (a person and the house named after them) would be forced together. Today's split
  hides this by accident. Tier 1 (`type_conventions.yaml`) needs a way to declare
  "these are distinct" — at minimum, report any subject whose original type shares
  are near 50/50 between two non-adjacent types (`npc` vs `location`).
- **Precision decision.** Which dossier a fact lands in is a scope decision. Every
  tier is either a GM ruling or a deterministic rule, and every outcome is listed in
  `type_resolution.md`; nothing is decided by a model.

## 6. How we will know it works

Replay on OOTA's existing corpus, no new extraction:

1. **Zero split dossiers** for every subject that resolves at tiers 1–4.
2. Reproduce the **109 GM merges** with no hand work: each merged group lands in one
   dossier, under the GM's `primary` type (tier 2 guarantees this for subjects with a
   ruling; the check is that nothing else overrides it).
3. Keep all **9 kept-separate** groups separate.
4. No fact typed `event`, `thread` or `date` changes type.
5. Count the tier-5 queue. If it is long, revisit the 60 % threshold before adding
   any model tie-breaker.

### 6.1 Replay result: the `monster` slice (2026-10-04)

Script: `~/src/dgx-fun/clef/ensemble-typing-eval/replay_489.py`. It reimplements the
chain beside the real bundling rules (`_norm_subject`, registry aliases,
`known_names`, `monster_vocab`) on the `per_chapter` corpus, for the 438 subjects with
at least one `monster` fact (50 of them named). 41 of the 64 GM rulings that involve a
`monster` file have their members in this corpus; the rest come from
`per_chapter_rerun`. Nothing is written.

| | Today | Tier 4 only (no GM data) | Tiers 2 + 4 | Tiers 2 + 3 + 4 (mapping not yet approved) |
|---|---|---|---|---|
| Named subjects split across types (of 50) | 43 | 9 | 1 | 1 |
| GM groups landing in one dossier type = GM primary (of 41) | 0 | 32 | 40 | 40 |
| GM groups landing in one *wrong* type | 1 | 1 | 0 | 0 |
| Named subjects queued (tier 5) | — | 9 | 0 | 0 |
| Dossiers | 667 | 592 | 577 | 577 |

- **Tier 4 alone is the honest test** — it is what new, unreviewed chapters get. When
  the vote decides, it matches the GM 32 times in 33. The one miss is `poison`, which
  the GM had already flagged as mis-subjected.
- **What tier 4 cannot decide is the right queue.** The 9 queued named subjects are
  Lolth, Zuggtmoy, Zuggtmoy's Spores, Faerzress, Zurkhwood, Malfire, Whistler, the
  Pudding King and Myconid Sovereigns — mostly the cases §4 asks about.
- **The one split left at tiers 2 + 4 is intended:** Myconid Sovereigns' kept-separate
  `faction` file (§3).
- **Tiers 2 + 4 are partly circular** — scored against the rulings tier 2 uses — so
  they show the chain honours rulings, not that it predicts them.
- **Tier 3 changes nothing on this slice** (it decides 5 subjects, same outcome).
- **The 60 % threshold holds.** Tier 4 only, swept:

  | Threshold | One type, correct | One type, wrong | Named subjects queued |
  |---|---|---|---|
  | 50 % | 34 | 4 | 4 |
  | 55–60 % | 32 | 1 | 9 |
  | 67 % | 22 | 1 | 21 |
  | 75 % | 21 | 1 | 22 |

Not yet replayed: the other entity types, and `per_chapter_rerun`.

## 7. Why not Clef (or any per-fact classifier)

Cloudflare's Clef decision model was tested for exactly this on 2026-10-03, because
picking one of eight types is the kind of closed choice it is built for. Per entity it
tied a free majority vote (82/92). Per fact it made splits on entities that were
fine. Its determinism does not help: it guarantees the same answer for the same
input, and every fact is a different input. The fix is to stop asking the question
per fact. The one role that measured well — an entity-level second opinion that
routes disagreements to the GM (§2) — is not specific to Clef.

## 8. The underlying flaw: rulings are recorded, not fed back

Split dossiers are a symptom. The ensemble pipeline has two compounding defects, and
entity-level typing fixes them for one field only.

**1. Extraction makes precision decisions with no checkpoint.** A fact's `type` is a
scope decision (which dossier it belongs in) and its `subject` is an identity
decision (who it is about). Extraction is a good drafter of both, but its per-fact
labels go straight into the bundle key, `(type, canonical subject)`, and from there
into the dossiers. That is the *LLM extracts → LLM structures* pattern: the draft is
treated as the decision.

**2. The GM's rulings are stored but not read.** Every correction the GM makes is
written somewhere the pipeline never consults:

| GM ruling | Lives in | Should feed | Feeds today |
|---|---|---|---|
| Type merges and the primary type | `.type_merge_decisions.json` | `facts_to_state` bundling | nothing — only `/ensemble-type-merge` reads it, to avoid re-asking |
| Kept-separate and re-subject notes (e.g. `faction_daz.md` is the patron thread) | the same file, as free-text `note` | subject resolution | nothing |
| Spellings | spell-pass glossary (`notes/vtt_transcription_corrections.md`) | subject canonicalisation | nothing — bundling reads registry aliases only (§5) |
| Bible corrections | `docs/TheUnderdark.md`, `docs/chapters/` | extractions | only on re-extraction — ch31's 2026-07-13 extraction still says "Zuggtomy" after the 2026-07-18 fix |

So every `facts_to_state` run rebuilds the splits the GM already merged (109 in
OOTA), and the rulings are applied again as cleanup instead of once as input. A
ruling made once should never have to be made twice.

### The principle

**Rulings are inputs, and the LLM proposes.** Resolve every precision field —
`type`, `subject` — against a ruling table *before* anything is built on it. A
proposal the table covers takes the ruling. One the table does not cover goes to a
queue, and the GM's answer becomes a new row. §2's chain is this principle applied to
`type`: tier 1–3 are ruling tables, tier 4 is a deterministic default, tier 5 is the
queue. The §6.1 replay shows the payoff: with the GM's merge rulings fed in (tier 2),
all 40 merged groups found are reproduced and no named subject is queued.

### Constraints

- **One authority per field, with a stated precedence.** Ruling stores already
  disagree — registry type vs. merge primary on 16 subjects (§4). Feeding both
  without an order is split-brain under another name. Each field gets one resolution
  chain, and every cross-store conflict is reported in `type_resolution.md`, not
  silently settled.
- **Rulings must be machine-readable.** Re-subject rulings exist today only as prose
  in `note`. To feed back they need a structured form (`resubject: {from, to}`).
- **Re-subjecting is per fact, and facts have no stable id.** Moving one fact to
  another subject is an identity ruling about a single fact, not an entity. Merged
  facts carry `type, subject, fact, source_quote, passes` — no id — so an override
  must key on something stable across re-extraction, such as chapter + normalised
  `source_quote`, and must report when its key stops matching.
- **Spelling has to reach bundling.** Either `load_bundles` canonicalises through the
  glossary as well as the registry, or glossary variants are promoted into registry
  aliases (a GM-approved name change). Which one is a GM decision; this proposal does
  not make it.
- **Stale extractions must be detectable.** A source fix only reaches the dossiers
  through re-extraction. Recording the source file's hash in each chapter's
  `manifest.json`, and warning when it no longer matches, makes stale extractions
  visible instead of silent.

### Order of work

1. **Type** — this proposal (tiers 1–5). Feeds `.type_merge_decisions.json` back.
2. **Spelling** — glossary or promoted aliases into subject canonicalisation, plus the
   stale-extraction check.
3. **Subject** — structured re-subject rulings, keyed per fact.

Each step removes one class of cleanup the GM currently repeats after every run.

