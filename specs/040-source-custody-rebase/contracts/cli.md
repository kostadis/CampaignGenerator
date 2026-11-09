# CLI Contract: `summary_native delta rebase` (+ `delta plan rebind`)

These commands extend spec 039's `delta` family (`specs/039-incremental-campaign-updates/contracts/cli.md`) and follow its conventions without exception:

- **Family flags:** `--campaign-dir`, `--config`, `--json`, `--force` (overwrite only what is already there), `--backend`/`--model`.
- **Selection:** `--source` is repeatable and never defaulted. There is no "all".
- **Exit codes:**

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | refusal |
| 2 | usage / empty selection |
| 3 | stale / conflict |
| 4 | partial |
| 5 | recovery required |

## New leaves

| Command | Purpose | Key arguments | Writes |
|---|---|---|---|
| `delta rebase inspect` | Every pinned historical source whose bytes differ from the active generation's custody (chain-aware), with expected/actual digests and old-byte availability per provider. No model call | `[--plan ID]` (also checks that plan's baseline) | none |
| `delta rebase prepare` | Create a rebase: recover old bytes (snapshot → git → file), verify, snapshot old and current, build the rebase plan (`kind: rebase`) and the impact set | `--source PATH…` (required; a source not stale per inspect is exit 2 "nothing to rebase"), `--old-bytes CHAPTER=PATH…`, `[--for-plan ID]` (pending delta whose candidates join the impact) | custody objects, `rebase/<id>/{inspection,snapshots,impact}.json`, plan r1 |
| `delta rebase show` | Render the review: per-source diffs, affected lines and annotations, unknown-impact members, follow-up consumers, repairs and decisions so far | `--plan ID` | `rebase/<id>/review.md` |
| `delta rebase propose` | Model-drafted repairs for affected lines only (drafts; never approved) | `--plan ID --backend --model` | grounding edit proposals |
| `delta rebase repair` | GM-authored repair for one affected line | `--plan ID --line LINE_ID --text TEXT --reason TEXT --reviewer NAME` | grounding edit proposal (origin `gm`) |
| `delta rebase repair --hold-entry` | Bulk hold: one explicit hold decision for EVERY affected baseline line citing one changed entry (a changed scene repeated across a document is otherwise one decision per line). Only the lines citing exactly that chapter and entry; a line that already has a proposal is left alone and reported; the entry must be one the impact lists (`REBASE_UNKNOWN_ENTRY`, exit 2). Every held line id is printed and written to the hold record | `--plan ID --hold-entry CH/ENTRY --reason TEXT --reviewer NAME` (reason and reviewer required, no default; not combinable with `--line`/`--text`) | one proposals revision and one decisions revision (decision `hold`, one per line, reason names the line), `rebase/<id>/holds-r<N>.json` |
| `delta rebase decide` | Per-source and per-unknown-member decisions | `--plan ID --reviewer NAME --source-decision CH=adopt-unaffected\|adopt-with-repairs\|reject…`, `--member-decision MEMBER=repaired\|held\|attested-unaffected…`, `--reason TEXT` (required for each `attested-unaffected` and `reject`) | `decisions-r<N>.json` |
| `delta rebind` (deviation: `plan` is itself a leaf, so `plan rebind` cannot coexist with `plan --source`) | Rebind a pending delta plan to the now-active rebase generation | `--plan ID --baseline GENERATION_ID` | plan r+1, `rebind-<plan>-r<N>.json` |

Repairs are approved, rejected or held with the existing `delta grounding decide PROPOSAL_ID --decision approve|reject|discuss|hold --reviewer NAME`. (`hold` is added to `DECISIONS`; a hold appends a marker under the line, see research R5.)

Everything after decisions uses existing leaves on the rebase plan id: `delta grounding check`, `delta grounding preview` (stages the gap-labelled range), `summary_native claims select|check`, the existing exact document signoffs (`delta review handoff`), `delta grounding apply`, `delta run status|resume`, `delta receipt`.

## Refusal messages (all name the chapter and the remedy)

| Code / exit | When |
|---|---|
| `REBASE_OLD_BYTES_UNAVAILABLE` / 1 | No provider found bytes hashing to the pin. Lists the providers tried |
| `REBASE_OLD_BYTES_MISMATCH` / 1 | Supplied or recovered bytes hash differently. Shows expected and actual |
| `REBASE_NOTHING_TO_REBASE` / 2 | The selected source matches its pin |
| `REBASE_SEMANTIC_CHANGE` / 1 | `adopt-unaffected` was requested with affected lines or annotations. Lists them |
| `REBASE_UNRULED_IMPACT` / 1 | `grounding check` on a rebase plan found the decisions missing, stale against what they bound, or incomplete (an unruled unknown member, or an affected line without a repair or hold) |
| `REBASE_UNKNOWN_ENTRY` / 2 | `rebase repair --hold-entry CH/ENTRY` names an entry no affected baseline line cites. Lists the entries that are cited |
| `REBASE_STALE` / 3 | The current bytes of a selected source, the active baseline, impact, edits, decisions or preview changed since they were bound. Names the input |
| `REBIND_NOT_CHILD` / 1 | `--baseline` is not active, or its lineage parent is not the plan's baseline |
| `CLAIMS_SOURCE_STALE` (existing code) | The message now includes the chapter, path, expected and actual digests, and `run: summary_native delta rebase inspect` |
