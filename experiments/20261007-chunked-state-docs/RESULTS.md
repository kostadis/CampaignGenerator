# Chunked Spark drafting of world_state + campaign_state — results (2026-10-07)

Question: does PR #504's chunked-on-Spark pattern (map per chunk → code check → stitch → small
reduce calls) produce better `world_state` / `campaign_state` drafts than 031's one-shot
`summary_native synth`?

Corpus: Out of the Abyss copy (`~/out-of-the-abyss/out-of-the-abyss`), ch 2–70, 67 chapters, 409 scenes,
443 audit items from `docs/tracking/tracking*.txt`. Read-only; nothing in the campaign was written.

- **Baseline**: `docs/summary_native/ch002-070/drafts/*.draft.md` — Opus 5.5 via `claude-code`, one call
  each, 610–660K-char prompt built from scene *synopses* + selected dossiers + moments.
- **Chunked**: `run1/{world_state,campaign_state}.chunked.md` — `qwen3.8-flash-next` on spark1 (+ spark2
  for the second half), 60 map calls over the *full* summaries (60K chars/chunk, mostly one chapter),
  9 reduce calls. One map pass feeds both documents.

## Design

| Section | Who decides |
|---|---|
| Canon Events Timeline, Completed Encounters & Quests | code: stitched map bullets in chapter order |
| NPC Current States | code: latest cited row per entity; identity = registry name/alias exact match; PCs dropped (players.yaml); `Unknown` never overrides a known status, but a later Unknown report is shown beside it |
| Audit: Tracking Claims | code: SUPPORTED iff some chunk tagged the item `SHOWN`; `BEGUN`-only items stay NOT FOUND with the evidence listed |
| Party, Factions, Key NPCs, Locations, Items, Threats, Resolved/Active threads, Party situation | reduce call, one per section, fed only the notes routed to it |

Between map and reduce, code drops any bullet that is uncited, cites outside its chunk, or quotes a span
that is not verbatim: 3,101 kept, 118 dropped (`run1/drops.md`).

## Numbers (`run1/comparison.json`)

| | world baseline | world chunked | campaign baseline | campaign chunked |
|---|---:|---:|---:|---:|
| chars | 23K | 249K | 70K | 141K |
| bullets | 258 | 1,509 | 605 | 1,058 |
| scenes cited (of 409) | 91 (22%) | 406 (99%) | 194 (47%) | 302 (74%) |
| chapters cited (of 67) | 54 | 67 | 65 | 66 |
| registry entities named | 91 | 283 | 251 | 327 |
| quoted spans verbatim (excl. audit) | 17/17 | 140/143 | 5/5 | 16/17 |
| malformed citations | — | 4 | — | 0 |
| NPC status rows | — | — | 50 | 198 (73 ⚠ not in registry) |

World_state chunked by section: Timeline 150K (928 bullets), Threats 33K, Locations 22K, Items 15K, Key NPCs 18K, Factions 9K, Party 8K.

## What the spot checks found

- **Chunked caught a baseline factual error.** Baseline world_state: "Level: 8 … no later level-up".
  Ch 63 says "The party leveled up to level nine." Chunked has Level 9 [ch 063 / 063.06]. The level-up
  is in a bullet, not a synopsis, so the one-shot prompt never saw it.
- **Code-built NPC table v1 contradicted itself** ("Ilvara Mizzrym — Alive" ch 2 and "Ilvara — Dead"
  ch 53) because rows keyed on the literal name. Fixed with registry identity; now one row each, matching the
  baseline for Ilvara, Sarith, Jimjar, Buppido, Glabbagool. v1 outputs kept as `*.chunked.v1.md`.
- **Reduce "later wins" can pick the wrong fact**: party name given as "Ember Grapple" (a running joke that
  ch 64's summary uses) instead of the adopted "Ember Vanguard". Baseline gets this right.
- **Audit: neither side is reliable alone.** Same totals (174 SUPPORTED each, coincidentally), 81% item
  agreement, 42 disagreements each way (`run1/audit_disagreements.txt`). Of 5 checked against the summaries:
  chunked right, baseline missed — level 9, Tempus shrine (055.02), Kestler (055.04); baseline right,
  chunked missed — Bloppblippodd (008.01), Alkrist's confession (061.07). Chunked also has visibly loose
  SUPPORTEDs (an item cited with an unrelated fact: "Echo 1 activated" ← crystals destroyed). Asking each map
  call to scan 443 items gives weak recall.

## Cost

- Map, single box (6 in flight): ~210–265 s per chunk, ≈1.4 chunks/min. Dual box (6 per box):
  31 chunks in 671 s, ≈2.8 chunks/min — ~2× (spark1 took 17, spark2 14).
- Reduce: 9 calls, 514 s wall (the Threats section alone, 33K chars out).
- Baseline: world 3.4 min; campaign 7.7 min after two failed attempts at 16K max tokens (9 + 14 min).

## Round 2 — DeepSeek-V4-Flash-0731 (cross-box TP=2), and the timeline split

Same prompts, chunks and code (`run2/`). The Canon Events Timeline is now its own file
(`canon_events_timeline.chunked.md`) in both runs; world_state carries a one-line pointer.

| | opus 1-shot | qwen chunked | DeepSeek chunked |
|---|---:|---:|---:|
| world_state chars (timeline excluded) | 23K | 107K | 237K |
| timeline file | — (4K in-doc) | 152K, 932 events | 429K, 2,006 events |
| world_state scene coverage, + timeline | 22% | 70%, 99% | 75%, 100% |
| world_state quoted spans verbatim | 17/17 | 44/44 | 268/270 |
| campaign_state chars | 70K | 139K | 220K |
| campaign_state scene coverage | 47% | 74% | 81% |
| NPC table rows | 50 | 198 | 230 |
| map bullets kept / dropped | — | 3,105 / 113 | 5,356 / 157 |
| hand-verified facts (16) | 12 | 10 | 12 |
| audit SUPPORTED | 174 | 174 | 253 (155 without the runaway chunk) |
| map wall time | — | 11 min (2 boxes, 31 chunks) + 20 min (1 box, 29) | 72 min (1 endpoint, 6 seqs) |
| reduce wall time | — | 9 min | 16 min |

Findings:

- **DeepSeek writes 2–3× more per chunk, quotes far more, and quotes accurately** (268/270).
- **Strict-format drops can silently flip a code-owned answer.** DeepSeek recorded Sarith's death but cited
  `[ch 031 / NPCs]`; the check dropped that row, so the ch 29 "Alive" row won. Fixed by accepting a section's own
  heading text (any case) as its key — an exact lookup, unknown sections still fail. Recovered ~75 DeepSeek
  bullets, 5 qwen. DeepSeek reduce was re-run on the corrected notes (`reduce.v1/` kept).
- **One DeepSeek map call ran away on the audit list** (ch 026): 139 audit bullets, 125 of them
  "X happened in a prior session [ch 026 / 026.01]", walking A1…A443 in order. Every citation is well-formed and
  in-chunk, so the code check passes them. 98 SUPPORTED verdicts rest on that chunk alone. Its other sections are
  normal. Deterministic guards that would catch it: require a verbatim quoted span from the chunk in every audit
  bullet (the span check already exists), and flag a chunk whose audit count is an outlier.
- On the 16 hand-verified facts the three tie (12/10/12) with different misses: Opus misses things only in
  bullets (level 9, Tempus shrine, Kestler); the chunked runs over-support loose audit items (Droki, Kalan).

## Round 3 — budgeted world_state + reference files (DeepSeek, `--world-budget`)

Why round 2 was too big: the reduce barely compressed (Factions 28.8K in → 28.5K out; qwen ~75–80% too)
because the prompt said "detail is the point, do not flatten" and set no budget, and DeepSeek's map wrote
~2× the notes. Fix: a world_state-only reduce prompt (`prompts/reduce_world.system.md`) with a hard word
budget per section and "choose what matters now"; every routed note is kept verbatim, grouped by subject, in
code-written `reference/{factions,npcs,locations,items,threats}.md`, linked from each section. campaign_state
is untouched (decision-driving; keeps its precision prompt). Only the 6 world reduce calls re-ran (~3 min).

| | opus 1-shot | DeepSeek round 2 | DeepSeek budgeted |
|---|---:|---:|---:|
| world_state chars | 23K | 237K | 16.5K |
| words vs budget (3,550) | — | — | 2,691 (every section under) |
| chapters cited / registry entities | 54 / 91 | 67 / 298 | 29 / 58 |
| invalid citations / quotes verbatim | 0 / 17 of 17 | 2 / 268 of 270 | 0 / 18 of 20 |
| reference files | — | — | 270K, 610 subjects, 887 notes |

Read-through: a usable "where things stand" briefing, current and specific. Errors found: **Daz (a PC) listed in
Key NPCs and fused with the House T'sarran spy**; **Jimjar listed as travelling with the party [ch 26]** while
Key NPCs correctly says he vanished in ch 48; Factions has Kalan "fled" (ch 65) where Key NPCs has him
reinstated (ch 67); the Staff of Power filed under party-held. Tolerable for world_state by the GM's standard
(it is a summary), and the PC one is cheap to prevent in code (drop PC subjects from the NPC notes, as the NPC
table already does). The model under-uses its budget (Key NPCs 340/900 words), so budgets can be raised if
the GM wants more breadth.

## Round 4 — Key NPCs from published dossiers, and a check-then-fix pass

**Dossiers** (OOTA copy; `summary_native build --force` because the copy's registry had changed, Opus
baselines backed up first in `baseline_backup/`): `npc-link` reproduced #504's goldens (222 / 1,619 / 1,045).
`npc-draft --recent-chapters 10` selected 30 global NPCs; drafted chunked on DeepSeek in 6 parallel processes,
39 min. **24 pass verify, 6 fail** (Buppido, Glabbagool, Jimjar, Sarith Kzekarit, Sylvira Savikas, The Flying
Iron Owlbear) — each on 1–2 quoted spans that paraphrase, or a quote without its source citation. The 24 were
published; the 6 were not (forcing them is the GM's call).

**Key NPCs from dossiers** (`npcs_from_dossiers.py` → `run2/world_state.dossiers.md`): code picks the published,
verify-pass dossiers ordered by last seen and reads ONLY `## Identity` + `## Last Observed State` (Secrets is
never read); one DeepSeek call renders one line each; code checks every line (one per NPC, citations from that
NPC's dossier only, quotes verbatim). 24/24 lines accepted, 0 fallbacks. The section is now correct where the
model-written one was wrong: Kalan "reinstated", Bookwyrm dead, no Daz. Gaps: the 6 unpublished NPCs, including
Glabbagool and Jimjar; walk-ons (Irony, Elian, Nibbles) come in via the recent-10 rule; Edvaldo's dossier state
reads as of ch 68 (a dossier fix, not a world_state one).

**Fix pass** (`fixpass.py`, Key NPCs skipped):

| | v0 (first build) | v1 | v2 (final gates) |
|---|---|---|---|
| wrong deletions | Bookwyrm, Avowed incoming | Gyrgum's key line | none |
| Jimjar stale "travelling with the party" | fixed | fixed | **not fixed** (fixer answered a no-op MOVE) |
| Kalan "fled" | missed (not flagged) | flagged, not fixed | flagged, not fixed |
| Staff of Power under party-held | flagged, unchanged | not flagged | rewritten, not moved |
| artifacts | — | 3 junk labels | 1 junk label `**<label>**` (bug fixed after) |

Gates that held: DELETE only on a code rule (player character, covered more recently in another section);
reviewer flags must cite real evidence (5 of 22 dropped in v1); MOVE refused to a section name / own group /
placeholder; every REPLACE verified (3–4 rejected per run for length or a new name).

**Finding: detection is dependable, model fixing is not.** The code detectors flag the right lines every run
(Kalan via the per-claim check, Jimjar via staleness). The fixer's choices vary run to run on the same flags and
it misuses actions. Applying its fixes automatically is not safe even with every gate; the useful output is
`corrections.md` as a GM review queue: flag + evidence + a verified proposed rewrite, accepted or rejected by
the GM.

## Round 5 — session prep as the test: docs as authority vs docs as pointer

Same beat ("The Avowed Readers arrive while the party holds the Book of Vile Darkness"), four independent runs
of gm-session-prep on the OOTA copy. Pointer variant = `skills_variant/gm-session-prep-pointer/SKILL.md`
(generated docs are an INDEX; verify every on-stage entity against its latest summary; summary wins; log
"Doc errors found"). Preps and source maps in `prep/`.

| Trap (verified against the summaries) | A new docs | B old docs | C pointer + new | D pointer + old |
|---|---|---|---|---|
| Sylvira "bedridden" (campaign_state, stale vs 067.03) | ✓ used ch67, flagged | ✗ used stale | ✓ doc error logged | ✗ "verified — agree" (checked the wrong mention) |
| Manshoon dossier's invented third simulacrum | ✓ flagged | n/a | ✓ doc error logged | n/a |
| Edvaldo dossier stale (ends ch68) | ✓ noticed | n/a | ✓ + root cause (no `Edvaldo` alias) | n/a |
| campaign_state "First Reader received them; Bookwyrm did not" | — | — | ✓ logged | ✓ logged |
| Doc errors surfaced | 1 (+conflicts) | 0 | 8 | 5 |
| Verification lookups / wall time | — / 6.0 min | — / 5.4 min | 36 checks, 11 searches / 5.7 min | 31 checks, 11 searches / 5.6 min |

- **The pointer variant is the best configuration (C)** and costs no extra wall time.
- **Doc quality still matters under verification.** D marked Sylvira "agree" after checking a mention that did
  not settle her current state; C got it right because the new world_state's annotation pointed at 067.03. A
  pointer has to point at the LATEST evidence, which is what the annotations and dossier citations are for.
- **"Doc errors found" is a free QA channel**: each prep run reports where a generated doc disagreed with a
  summary, with both citations — a fix-at-source queue. Root causes found this way: the registry lacks an
  `Edvaldo` alias (105 mentions in ch 69–70 unlinked, so his dossier stops at ch 68); the Manshoon dossier's
  reduce double-counted a simulacrum; campaign_state is stale (not rebuilt in this experiment).
- One of my annotations was mis-worded: `⚠ unverified: "information about Underdark events" is not in the
  summaries` — the summary has "information about events in the Underdark", so the span is a paraphrase, as
  flagged, but "not in the summaries" overstates it; it should read "not verbatim".

## Round 6 — Qwen3-Next-80B-A3B (MTP-2, 8 seqs/box, both boxes) for throughput

`run3/`, same prompts and chunks; spun up with `MAX_SEQS=8 SPEC_TOKENS=2 GPU_UTIL=0.80`, prefix caching OFF
(the v0.22.0 image predates the Mamba block-size fix; APC is immaterial for decode-bound work anyway).

| | qwen3.8 (run1) | DeepSeek (run2) | **Qwen3-Next (run3)** |
|---|---|---|---|
| map output | 468K | 1,149K | **1,413K** |
| of which Audit section | 11% | 10% | **42%** |
| map wall, 60 chunks | ~32 min (half 1 box) | 72 min | **30.5 min** |
| useful (non-audit) tok/s | ~55 (~90 if 2 boxes throughout) | ~60 | **~112** |
| map drops | 113 | 157 | **2,664** (≈2,150 Audit) |
| hand-verified facts (16) | 10 | 12 | 11 |
| world_state invalid citations | 5 | 2 | **0** |
| world_state quotes verbatim | 44/44 | 268/270 | **184/300** |

- **Throughput: ~2× DeepSeek's useful output in under half the time.** Comparable content volume (Events
  1,569 vs 2,006; World 974 vs 987; Threads 560 vs 432).
- **The Audit list runs away in nearly every chunk**: invented ids past A443, and "BEGUN — not yet reached X"
  for items the chunk never touches, despite "leave out every audit question the chunk does not bear on".
  42% of output tokens. Code kept the verdicts clean, but the cost is real — moving the audit out of the map
  (#505) would make this model ~40% faster still.
- **Its reduce paraphrases inside quotation marks** (116 non-verbatim quotes in world_state); map notes are
  span-checked so these come from the reduce. For a Claude reader that treats quotes as canon, that matters.
- Suggests a **split**: Qwen3-Next for the map (bulk, code-checked), a faithful model for the 9 small reduce calls
  (DeepSeek, or Claude) — or span-check the reduce output and annotate (`⚠ unverified:`) as `annotate.py` does.

## Round 7 — Claude for the reduce step only (Qwen3-Next map notes, cached)

`--backend claude-code` (subscription, `claude -p`, thinking off), 3 calls at a time; the map is run3's, so only
the 9 reduce calls differ. The `run3_{sonnet,sonnet_hi,opus,opus_lo}/` folders are committed without their `map/`
copies (byte-identical to `run3/map/`); to re-run one, copy `run3/map` into it first. Code-built sections (timeline, completed, NPC table, audit) are identical across rows.

| reduce model | slowest call | sum of calls | world_state chars | quotes verbatim | invalid cites | scene cov. | entities |
|---|---|---|---|---|---|---|---|
| Qwen3-Next (Spark) | 661 s | 3,260 s | 208K | 184/300 (61%) | 0 | 61% | 252 |
| **Sonnet 5.5 medium** | **49 s** | **308 s** | 64K | **44/47 (94%)** | 2 | 51% | 206 |
| Sonnet 5.5 high | 107 s | 537 s | 80K | 50/54 (93%) | 0 | 52% | 210 |
| Opus 5.5 low | 84 s | 365 s | 53K | 39/49 (80%) | 0 | 43% | 158 |
| Opus 5.5 medium | 126 s | 639 s | 86K | 52/66 (79%) | 0 | 55% | 210 |

- All Claude reduces condense (53–86K vs 208K) and are 5–20× faster per call than the Spark reduce.
- **Sonnet medium is the pick**: best quote fidelity, fastest, cheapest (~$1–1.50 per rebuild at API rates;
  $0 marginal on the subscription). Sonnet high adds ~25% content at ~1.7× the time, same fidelity.
- Opus's lower quote score is mostly quotation marks around *note* text (NPC-table dispositions such as
  "Grateful and resigned") and light paraphrase — the reduce prompt permits quoting notes, so this is partly the
  prompt's fault. For a Claude reader that treats quotes as speech, the prompt should restrict quotation marks to
  words spoken or written in the summaries. Opus low is the thinnest (43% scene coverage, 158 entities).
- campaign_state's quote counts are dominated by the code-written audit item titles and are not a model signal.

## Verdict

- **Coverage/detail: yes, clearly.** Near-total scene coverage, 3× the entities, and it reads details the
  synopsis-fed one-shot cannot see (the level-up).
- **Usability as a grounding doc: not as is.** world_state is 10× the baseline; the 150K timeline alone is
  ~37K tokens. The Timeline (and probably Completed) want to be their own files, or a code-side filter.
- **Precision work belongs in code + registry**, not the reduce: identity and status succeeded only once
  code did them with the registry. The audit should not ride along in the map; per-item checking (one item,
  its candidate chapters) is the obvious next experiment.
