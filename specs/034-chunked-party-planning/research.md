# Research: Chunked, Code-Checked Party and Planning Documents

**Feature**: `specs/034-chunked-party-planning/` | **Date**: 2026-10-08

Measurements below come from the cached Out of the Abyss notes of spec 033's T061 run: chapters 2–70, 60 chunks, Qwen3-Next. They are kept in the session scratchpad as `qwen_notes/`, a snapshot of `oota/docs/summary_native/ch002-070/state/notes/`.

| Kind | Notes |
|---|---|
| event | 1,302 |
| world | 941 |
| thread | 564 |
| status_row | 490 |
| party | 434 |
| concluded | 379 |

The design source for thread identity is `dgx-fun/survey-grounding/main.tex`: approach 9 (state stores and projections), F3, F8, and "Rulings must be inputs".

---

## R1 — Party notes must state their subject: change the extraction grammar

**Finding.** Code cannot attribute today's party bullets:
- **No leading name:** 258 of 434 notes.
- **Field labels instead of names:** "Level or rank" (6), "Group name" (10), "Next intention" (4), and others.
- **Em dash instead of colon:** some notes use `—` where others use `:` (`- Gyrgum — Cast Glyph…`).
- **Companions mixed in:** Glabbagool (12), Jimjar, Ront, Prince Derendil and Stool sit beside the player characters.
- **Spell levels:** 33 notes say "level", many of them spell levels ("4th-level slot", "Glyph of Warding (3rd level)").

**Decision.** The `## Party` section of `prompts/state.extract.system.md` adopts the World grammar:
- `- **Subject** — fact [cite]`, where Subject is one character's name or exactly `Party`.
- A level gets its own row: `- [LEVEL] **Subject** — N [cite]`.

`notes.check_chunk` then:
- sets `Note.subject` for party notes;
- drops a bullet with no bold subject (`missing-party-subject`);
- for a `[LEVEL]` row, drops it (`level-not-in-cited-text`) unless one of the cited sections contains N:
  - written as a digit, a word or an ordinal ("9", "nine", "9th", "ninth");
  - inside a level phrase (`level N`, `Nth level`, `Nth-level`, `levels? (?:up )?to N`, `reach(?:es|ed)? (?:level )?N`);
  - not followed by `spell`, `slot` or `spells`.

The party prose sections of world_state and campaign_state still receive the same note text, so neither document changes shape.

**Rationale.** Code has to settle attribution, and it can only settle what the extraction states (constitution II; F2: atomised text loses attribution unless it is carried). A level is the single most-wrong fact of the one-shot party, and a checkable row turns it into a fact code verifies rather than a sentence a model infers.

**Cost.** The system prompt is part of the cache key (`notes.cache_key`), so every chunk is re-extracted once (12.6 min on two Sparks at T061). That satisfies FR-002's "not reused silently" automatically. The run record shows `0 cached`.

**Alternatives rejected.**
- *Parse today's labels.* That means heuristics over 258 unlabelled notes and field-label words, which is attribution by guesswork.
- *A separate party-only map pass.* This violates FR-001 (one pass feeds all four) and doubles extraction time. Constitution VII prefers narrower passes when depth regresses, but there is no evidence of regression here: the Party section already exists. It only lacked a subject.

## R2 — Attribution of party notes (code)

**Decision.** `party_notes.attribute(results, identity, party_names)` (deterministic):

1. Subject `Party` (casefold) → **party-wide**.
2. Otherwise resolve the subject through `state_sections.load_identity`'s `forms`, by exact casefolded name or alias.
   - If the canonical name, or the raw subject, is a player character, the note is attributed to that character. Player characters are `players.yaml` `plays` plus `party.yaml` character names, each mapped through `forms`.
   - The whole subject is resolved first. Only if it resolves to nothing is it split (on `,`, ` and `, `&`), so a registry entity named "Topsy and Turvy" stays one companion. A split subject ("Daz and Zalthir") is attributed to each player character among the pieces, and only if every piece resolves.
3. A subject that resolves to a non-player-character entity → **companion**.
4. Anything else → **unattributed**, listed in `party_report.md` with the note text and citation. It is never guessed.

**Rationale.** This is the same identity rule as spec 033's NPC table (FR-009 of 033), with no similarity matching.

## R3 — Level (code)

**Decision.** For each character, the latest `[LEVEL]` row whose subject is that character, or `Party`, whichever has the later first chapter. A character row wins a tie. With no row, the section's code-written level line reads `Level: not recorded in the summaries (sheet says N)`, with N parsed from the sheet's `Level` field if present, else `sheet gives none`. The level line is **code-built**, prepended to the model's section body, and never written by the model.

## R4 — Thread identity: the GM's thread registry, retargeted (GM decision 2026-10-08)

**Finding.**
- 554 distinct thread names across 564 notes; 550 appear exactly once.
- By exact name, 505 threads would count as "open".
- Each extraction call sees only its chunk, so names drift by construction.
- No summary section authors threads: `## Session-End State` appears in 1 of 67 summaries.

**Decision.** `docs/thread_registry.yaml` is the identity authority, in its existing schema (`id, title, aliases, status, opened, log[]`). It is read through `pipelines/grounding/thread_registry.py`'s `load_registry`, `norm_title` and `match_thread`, which are the single seam. They move into `campaignlib/thread_registry.py` so `pipelines/summary_native` does not import a CLI module; the CLI re-imports them.

`thread_attach.attach(results, registry)` is deterministic:
- A thread note attaches to the one thread whose title or alias `norm_title`-matches the note's bold name.
- A name matching two threads is **ambiguous**: reported, never attached.
- Open/closed: the registry `status` wins when it is set to anything other than `open`. Otherwise the thread is open iff its latest attached note's tag is `OPENED` or `ADVANCED`. A `dormant` thread is listed in its own code-built block (title plus latest attached note, verbatim), never as model prose (GM decision 2026-10-08).
- Latest activity is the maximum `first_chapter` of the attached notes.

**Rationale.** F8 and "Rulings must be inputs". Approach 9's store design was sound and only its inputs were bad (the survey's own diagnosis).

**Alternatives rejected.**
- *Exact name only* fails on the measurements above.
- *Feeding the extraction the registry titles* lets the model make the identity decision (F8).
- *Embedding clusters* run into F3: similarity measures paraphrase, not identity.
- *The model deciding openness from the whole ledger*, as campaign_state does today, puts a precision decision in a model.

## R5 — Thread proposals: model-grouped, code-checked, GM-ratified

**Finding.** Approach 9 stalled at 4 ratified threads against 148 pending one-name proposals. Out of the Abyss would start with about 550.

**Decision.** A new model step, `summary_native thread-propose --since --until`, runs in four stages.

**Inputs.** Every *unattached* checked thread note, each with a stable id (R6) and given as `id | ch | tag | name | text`, in chapter order. Also every ratified thread: id, title, aliases, and its latest attached note. Notes whose earlier grouping the GM rejected are left out (R7).

**Call.** The model returns JSON:

```json
{"groups": [{"kind": "new", "title": "…", "members": ["n-…"]},
            {"kind": "continues", "thread": "<id>", "members": ["n-…"]}]}
```

The default is the prose backend from 033: `claude-code`, Sonnet 5.5, medium effort.

**Batching.** If the input exceeds `--max-input-chars` (default 150,000; OOTA's 554 notes are about 140K), notes are sent in chapter-ordered batches. Every batch sees the same ratified threads and nothing else: no batch sees another batch's proposals, so no model output feeds another model call (constitution II). A thread split across batches becomes two proposals. The GM joins them when ratifying, by ratifying one as `new` and the other as `continues` it, or by editing members.

**Check (code, `thread_check.py`).** Each of these is dropped and reported:
- an unknown member id;
- a member that is already attached;
- a member claimed by two groups (removed from both; spec US3 AS2);
- a `continues` group naming a missing thread;
- a group left with no members.

Every unattached note in no valid group becomes a single-note proposal.

**Write.** Proposals are merged into the existing proposals file (`projections.yaml` `thread_proposals`, default `docs/ensemble/thread_proposals.yaml`) as a new shape, alongside the existing name-keyed proposals:

```yaml
- key: g-<sha of sorted member ids>
  kind: new | continues
  title: …            # suggested; the GM edits it
  thread: <id>        # continues only
  members: [{id, chapter, tag, name, text, cite}]
  status: pending
  source: summary_native ch002-070 run <run_id>
```

Rulings already in the file (by `key`) are preserved. The ensemble harvest (`propose --corpus`) is unchanged and keeps writing name-keyed proposals for the campaigns that use it.

**What decision this removes from the human.** None. The model drafts candidate groupings. Nothing reaches the registry or a document until the GM ratifies (constitution II; the feedback rule "LLM surfaces candidates, not decisions").

**Alternatives rejected.**
- *Code grouping by normalised name only*: about 550 proposals (approach 9's failure).
- *Asking the model to also decide status*: status is code's job (R4).

## R6 — Stable note ids

**Decision.** `note_id = "n-" + sha1(f"{first_chapter:03d}|{kind}|{text}")[:10]`. This is stable across re-extraction when the text is unchanged. A re-extraction that changes text changes the id: the old ruling's members no longer exist, and they are reported as stale rulings (`thread_check` lists a ratified group whose members vanished). The ratified thread's aliases still attach the new notes by name wherever the names repeat.

## R7 — Ratify, split, reject (extending the existing verbs)

**Decision.** `thread_registry ratify` accepts a group proposal by `--key` with the GM's edited `--plan`:

```yaml
{id, title, status, aliases_add: [...], log: [{chapter, change, summary, cite}]}
```

`derive_plan` builds the starting plan from the members:
- log rows in chapter order;
- `change` from each member's tag (`OPENED` → opened, `ADVANCED` → advanced, and so on);
- `summary` = the note text;
- `cite` = the note's citation;
- `aliases_add` = the distinct member names minus the title.

A `continues` proposal appends log rows and aliases to its thread. One write per file (existing D18 rule).

- **Split** is `ratify` with a plan listing a subset of the members. The remaining members return as a new pending proposal with key `g-<sha of remainder>`.
- **Reject** is `rule --key … --status rejected`. A rejected group's members are excluded from future model grouping input and offered as single-note proposals (spec US3 AS4).

The `--plan` requirement stays, so there is no accept-as-proposed button (existing SC-004 rule).

## R8 — planning's NPC Dossiers from published dossiers

**Decision.**
- **Reuse:** `key_npcs.select_key_npcs`, `plan_key_npcs` and `refusal_message`, and the `missing_dossiers.json` write.
- **Selection:** planning-config tracked NPCs (canonicalised by `forms`) plus the recent/recurring selection, plus `--name`.
- **New view:** `key_npcs.planning_view(path)` reads `## Identity`, `## Personality and Motivations`, `## Last Observed State` and `## Relationships` by the same one-pass, held-heading-only parser. `## Secrets` is not in its take-set, and `tests/test_state_docs_no_secrets.py` is extended to it.
- **Model call:** one call writes a `### Name` block per NPC with three labelled lines (Status and location; Goals; Relationships), each cited. The block is checked like `verify_line`: citations only from that NPC's dossier, quotes verbatim, and the right heading set and order. A failing block is replaced by the dossier's own first Last Observed State sentence, and the substitution is reported.
- **Pointer:** each block ends with `→ docs/npcs/<slug>.md`.
- **Fallbacks:** the refusal and `--fallback-npc-lines` behave as in world_state, with the same `KEY_NPC_FALLBACK_MARK`.

## R9 — Factions, Threat Tracker, DM Notes, Party Overview and Dynamics

- **Faction States.**
  - **Selection (code):** planning-config factions, plus every `[FACTION]` subject in the checked notes. Each subject is canonicalised by `forms`, and unresolved subjects key on themselves, as in 033's reference files.
  - **Order:** by latest note, newest first.
  - **Writing:** one call writes a `### Name` block per faction from that faction's notes (grouped in the prompt). Code checks the heading set and order. A failing block becomes the faction's latest note, verbatim.
  - **Bounds:** within `planning_budgets["Faction States"]`. With more than `DEFAULT_MAX_FACTIONS` (20) selected, only the 20 most recently active are written. The rest are listed by name with a pointer to `reference/factions.md`, so code makes the scope cut and reports it.
- **Threat Tracker.** Code-built table `| Score | Subject | Candidate events | Trigger text |`, one row per configured, non-trackless score. With none configured it is the sentinel (`NO_ARC_SENTINEL`, unchanged). The candidate cell comes from R10.
- **DM Notes.** One call. Inputs: the open ratified threads' latest notes, the NPC status table, and the last chunk's evidence. The system prompt requires every line to be cited and labelled as a suggestion. Code prefixes the section with `_Suggestions for the GM, not events._`, and the annotators run on it.
- **Party Overview / Party Dynamics.** One call each, from the party-wide notes plus the latest two notes per character, within `party_budgets`.
- **Characters.** One call per configured character, given only that character's notes, sheet and backstory. Code prepends the R3 level line and the `### Name` heading, so the model writes the body only. Unsupported sheet claims are listed under `Unsupported by the summaries:`, as in today's prompt rule.

## R10 — Arc-score candidates

**Decision.** One call per configured, non-trackless score. It receives the subject's checked notes (by `forms` canonical subject over party notes for a player character, and over `[NPC]`/`[FACTION]`/status notes for planning entities) and the mechanic file's text. It returns lines of the form `- <event> [cite] — trigger: "<verbatim trigger text>"`.

`arc_check.py` (deterministic) drops a line for any of these reasons:
- its citation is not among the subject's checked notes' citations (`cite-not-in-notes`);
- the trigger is not verbatim in the mechanic file (`trigger not verbatim`, via `npc_check._contains`);
- `arc_check.states_a_value` says it states a current value, running total or threshold crossed (`states a value`). The first version was one regex, `\b(score|total|value|points?)\b[^.]{0,30}\d|\bnow (?:at )?\d|\bthreshold\b[^.]{0,30}(?:reached|crossed|met)`; #526 replaced it with the rules and verdict table in [arc_value_check.md](arc_value_check.md) (real-campaign measurement still pending).

Survivors go in party under `#### Candidate Arc Score Events` in the character section, and in planning's Threat Tracker cell. Drops go in `arc_report.md`.

## R11 — Retiring the one-shot path

**Decision.** `run_synth`'s one-shot body is deleted, along with `prompts/party.system.md`, `prompts/planning.system.md` and the `context.build_context` upstream-draft assembly (`--world-state`/`--campaign-state` blocks).
- `schema.STATE_DOCS = schema.DOCS`.
- `schema.draft_dir` always returns `state/drafts`.
- `context.party_config_block` / `planning_config_block` are replaced by structured loaders returning the resolved characters/entries. The renderers that built a prompt block go.
- **Refused with replacement messages (exit 2):** `--parts` (all four docs), `--world-state`, `--campaign-state`, and `--audit` (unchanged).
- `--name`, `--recent-chapters` and `--recurring-min` are refused for party, because it selects no NPCs.
- The old one-shot drafts under `<range>/drafts/` are plain files. A note in the how-to says they are superseded. No migration is needed (XIII: no state changes shape).

**Rationale.** Single-user migrate-and-delete (memory rule). Constitution: no dual paths.

## R12 — Budgets

**Decision.** Two new strict blocks sit beside the world_state `budgets` in `grounding.yaml` `summary_native.prose`: `party_budgets` and `planning_budgets`. This is additive, with no shape change to `budgets`. The defaults are declared once in `schema.py`:

```
DEFAULT_PARTY_BUDGETS    = {"Party Overview": 300, "Characters": 500 (per character), "Party Dynamics": 300}
DEFAULT_PLANNING_BUDGETS = {"NPC Dossiers": 1500, "Faction States": 600, "Active Plots": 1200, "DM Notes": 400}
```

These are initial values. Quickstart S1 measures the one-shot baselines before the old path is deleted, and SC-006 is checked against them. If a default turns out larger than the baseline, it is lowered in the same feature.

## R13 — Reading contract per document

**Decision.** `state_sections.reading_contract` takes a `doc` argument.
- The Key NPCs paragraph becomes "lines ending `→ docs/npcs/<slug>.md`", under `## Key NPCs` for world_state and `## NPC Dossiers` for planning.
- The thread paragraph is planning-only. It explains the ratified and unratified layers of Active Plots and where the proposals queue is.
- The reference-file list names only the files the document points to.
  - **party:** `reference/party.md` (new: party notes grouped by attributed character, with `Companions` and `Unattributed` groups).
  - **planning:** `reference/factions.md`, `reference/threads.md` and `reference/npcs.md`.
- The `summary_native pointers:` comment and `check-pointers` work unchanged (#510).

## R14 — Annotation

**Decision.** `annotate` runs at the end of `synth party|planning` as for the other two documents. `SKIP_SECTIONS` gains `## Threat Tracker` and `## NPC Dossiers` (dossier-sourced), plus the unratified-notes subsection of `## Active Plots` (verbatim notes, code-built). The PC-in-NPC removal applies to `## Faction States` and `## NPC Dossiers` entries. It never applies to party's character sections, where player characters belong; `Entry.group` already separates these. `tests/test_annotate_never_rewrites.py` is extended to party and planning.

## R15 — Where things run and reach

- **Engine:**
  - `summary_native synth party|planning` (rewired);
  - `summary_native thread-propose` (new);
  - `thread_registry ratify|rule` (extended for group proposals).
- **Web:**
  - `SummaryNative.vue`: party and planning use the same step UI as world_state and campaign_state (backend/model/effort, `--fallback-npc-lines` for planning, `--force`, `--dump-only`).
  - `Threads.vue` gains a "Propose groupings (summary-native range)" step and renders group proposals with their members.
  - The ratify editor gains member and alias editing.
- **Routes:** `GET /api/projections/threads/run/group-propose` streams `summary_native thread-propose`. `POST /api/projections/threads/ratify` accepts `key` + `plan`. The synth routes lose `parts`, `world_state` and `campaign_state` and gain `fallback_npc_lines` for planning.

## R16 — Testing approach

- **Fake model client:** as in 033. New fixtures: a party note set with labelled/companion/unattributed/level/spell-level cases; a registry with two ratified threads, one aliased; thread notes with drift; a planning config with one NPC and one PC arc score with mechanic files; a dossier with Secrets canary sections and a Relationships section.
- **No-LLM guard:** `party_notes`, `thread_attach`, `thread_check` and `arc_check` join `GUARDED` in `tests/test_summary_native_no_llm.py`. `synth` and `thread_propose` are the model steps.
- **Code-built sections:** a byte-identical rebuild test.
- **Real-data validation:** Quickstart S1–S6 on the OOTA copy.
