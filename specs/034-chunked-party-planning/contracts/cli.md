# CLI Contract: party, planning, thread proposals

Every command runs from the campaign root (`<cwd>/config/config.yaml`, no fallback). Exit codes follow spec 033:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | blocking validation |
| 2 | refused before any model call |
| 3 | incomplete draft (a section missing) |
| 4 | model call failed |

## `summary_native extract` (changed prompt, same flags)

The `## Party` grammar changes (research R1). The first run after this feature re-extracts every chunk, because the prompt is part of the cache key, and reports `0 cached`. New drop reasons in `drops.md`:

- `missing-party-subject`: a party bullet without a leading `**Subject**`.
- `malformed-level-row`: a `[LEVEL]` row with no readable number.
- `level-not-in-cited-text`: a `[LEVEL]` row whose number is not stated in a level phrase of a cited section.

## `summary_native synth party | planning` (rewired)

```text
summary_native synth party    --since A --until B [--party-config FILE]
                              [--force] [--dump-only] [--max-tokens N]
                              [--backend … --model … --endpoint … --claude-code-effort …]
summary_native synth planning --since A --until B [--planning-config FILE]
                              [--name NAME …] [--recent-chapters N] [--recurring-min N]
                              [--fallback-npc-lines]
                              [--force] [--dump-only] [--max-tokens N]
                              [--backend … --model … --endpoint … --claude-code-effort …]
```

- **Inputs:**
  - spec 033's checked notes for exactly the range;
  - the corpus;
  - the entity registry and `players.yaml`;
  - `party.yaml` (party only; player-character arc scores live there, never in planning);
  - `planning.yaml`;
  - published dossiers (planning);
  - `docs/thread_registry.yaml` (planning; also campaign_state's two thread sections, #530).
- **Backend:**
  - Defaults: flag > `grounding.yaml summary_native.prose` > `schema.DEFAULT_PROSE_*`, the same as world_state.
  - Budgets: `summary_native.prose.party_budgets` / `.planning_budgets`.
- **Output:** `state/drafts/{party,planning}.draft.md` plus the reports in `data-model.md`. Annotation runs at the end, as for the other two documents. Nothing is written to `docs/`.
- **planning, missing dossiers:** with default flags, a selected NPC without a published, verification-passing dossier refuses (exit 2), naming each NPC and its dossier state. `--fallback-npc-lines` writes the marked code-built line instead, for this run only.
- **planning, thread registry:** an absent or empty registry is not a refusal. Active Plots carries the "No ratified thread …" line and the unratified notes. A registry that fails `thread_registry check` is refused (exit 2) with the check's findings. **campaign_state (#530)** reads the registry the same way for `## Resolved Plot Threads` (closed ratified threads) and `## Active Quests & Open Threads` (open ratified threads, dormant block, unratified pointer): the same refusals, an absent registry is the pointer-only form with no model call, and `inputs.thread_registry_sha256` is in its run record. It writes `campaign_threads_report.md` beside `threads_report.md`.

**Refusals added (exit 2, before any model call), each naming its replacement:**

| Flag / case | Message (substance) |
|---|---|
| `--parts N` (any document) | "`--parts` is retired: every document is built one call per section from the checked notes" |
| `--world-state FILE`, `--campaign-state FILE` | "upstream drafts are no longer prompt context: party and planning build from the checked notes; review those documents on their own" |
| `--name`, `--recent-chapters`, `--recurring-min` with `party` | "party selects no NPCs; these apply to planning and world_state" |
| `--fallback-npc-lines` with `party` or `campaign_state` | "applies to world_state and planning only" |
| no checked notes for the range | "no checked notes for ch A–B; run `summary_native extract --since A --until B`" (as 033) |
| notes extracted under the old party grammar (`notes/manifest.json` prompt sha ≠ current) | "the party notes predate the subject grammar; run `summary_native extract --since A --until B` (it re-extracts every chunk)" |
| `party.yaml` missing or with no characters | as today (`context.DocConfigError` text) |

## `summary_native thread-propose` (new, model step)

```text
summary_native thread-propose --since A --until B          # both required: refused (exit 2) without them
                              [--max-input-chars N] [--max-tokens N] [--dump-only]
                              [--backend … --model … --endpoint … --claude-code-effort …]
```

- **Reads:** the checked thread notes for the range, `docs/thread_registry.yaml`, and the proposals file (path from `projections.yaml thread_proposals`, default `docs/ensemble/thread_proposals.yaml`).
- **Attaches first** (code, R4). Only unattached notes, minus members of rejected, deferred and ratified groups, are sent. A ratified member that is unattached (its alias was removed) is offered again by code as a pending `single` and listed under "Ratified but no longer attached (alias removed?)" in `propose_report.md` (#525).
- **Writes:**
  - group proposals merged into the proposals file, with existing rulings preserved by `key`; a replaced pending group's members outside the run's range stay as pending `single` proposals (#524) and are named in the report and on stdout (`note: replaced pending group g-… (…): kept N member(s) outside the run's range as single proposals: …`);
  - `state/threads/propose.{user,out}.md`;
  - `state/threads/propose_report.md` (including "Excluded and pinned notes no longer on disk (ruling may not hold)": a thread's `excluded_notes` id found in no range's notes, reported and never removed, #529);
  - a run record.

  It never writes the registry.
- **Prints:** `threads: N notes — A attached to R ratified threads, U unattached → G group proposals (S single), D dropped (see propose_report.md)`.
- **Exits:** 2 for a missing range, missing notes or a registry failing `check`; 4 for a model failure. With `--dump-only` it writes prompts only.

## `thread_registry` (extended verbs)

```text
thread_registry ratify --key g-… --plan FILE|-        # group proposal; the plan is the GM's edit of `ratify --key g-… --emit-plan`
thread_registry ratify --key g-… --emit-plan          # prints derive_plan(members) for the GM to edit (never writes)
thread_registry rule   --key g-… --status rejected|deferred [--note TEXT]
thread_registry alias  --id T --alias NAME           # also notes the excluded notes of T that carry NAME (#529)
```

- **Plan shape:** `{id, title, status, opened, aliases_add: [..], members: [ids], log: [{chapter, change, summary, cite}]}`.
  - A `continues` plan names `thread: <id>` and has no `title`.
  - `members` listing a subset of the proposal's members is a **split**: the remainder becomes a new pending group, and its note ids are recorded on the ratified thread as `excluded_notes` so a shared name cannot attach them (#529). Ratifying an excluded note into the same thread removes its id in the same write.
- **Validation before the single write:** every log row's chapter is ≥ 1; `id` is new for `new`; the thread exists for `continues`; aliases do not collide with another thread's title or alias (a derived alias that is a ratified member's own name and belongs to another thread is dropped with a note and the member pinned in `included_notes` instead, #529); an alias that only a member left out of `members` carries is refused (#529).
- **Existing verbs:** `--norm` keeps working unchanged for name-keyed (ensemble) proposals.
