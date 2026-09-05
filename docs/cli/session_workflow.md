# Session production and shared review

For the user-facing flow, start with [Session cycle: what to do, and where](session_cycle_walkthrough.md). This page is the command and data-contract reference.

Open **Session → Production review** (`/workflow/cycle`) to inspect runs,
read preserved evidence, review findings, and approve a draft. Set the session
directory inside the active campaign, then Load or Initialize. Reload and CLI
changes read the same `session_workflow.yaml`. No state depends on browser storage.

The CLI uses the same request JSON as the editor's interchange panel:

```bash
session_workflow init --campaign-dir /campaign --session-dir summaries/001 --config /campaign/config/config.yaml
session_workflow status --campaign-dir /campaign --session-dir summaries/001 --json
session_workflow start --campaign-dir /campaign --session-dir summaries/001 --expected-revision 1 --request start.json
```

Each mutation requires the revision last read from status. Requests have exactly
the keyword fields below; unexpected fields refuse rather than disappear.

| Operation | JSON request fields |
|---|---|
| start | stage, selection (explicit IDs), inputs (paths), generation, dependencies (approved run IDs), required_checks |
| submit | run_id, outputs (session-relative paths), generation |
| check | run_id, check (name, status, sources, findings, producer, at) |
| decide | run_id, decisions (individual finding_id, finding_sha256, decision, at; optional actor, rationale, group) |
| approve | run_id, draft_binding (from status); optional actor, rationale |
| apply | run_id, finding_ids (explicitly selected, individually approved changes) |
| select-version | run_id (approved and fresh) |
| export | run_id |
| import | document (validated exported JSON with explicit decisions) |
| evidence | an Evidence object from status or export |
| recover | empty object; complete a journaled interrupted replacement |
| migrate | config, artifacts, dry_run, force (see migration guide) |

`generation` records backend, model, effort (or null), producer, command, and
available usage. It must describe the actual producer. Use a distinct run when
changing settings. A skill receives a resolved pending task, works natively,
and submits findings or output references. It never approves its own draft.
Corrected and smoothed material is derived; never present it as verbatim.

Check `sources` must bind every output in the run. Findings include an ID, scene,
evidence, location, description, proposed action, explicit consequences for all
three decisions, and optional rule provenance and exact replacement. Evidence
objects come from status: path, sha256, snapshot, label. Check status `skipped`
or `failed` remains visible and blocks draft approval. Unmarked findings and
Discuss remain unresolved. Group discussions still produce individual records.

The editor offers per-finding Approve/Reject/Discuss controls, saved discussion notes, explicit bulk selection, scene filters, evidence preview, JSON download/import, and separate draft sign-off. Copy handoff for agent supplies the campaign/session/run and saved choices for chat; the agent reloads the disk record before acting. Selecting all means
materializing the displayed IDs; clearing selection disables batch actions.
Approving a proposed change does not apply it. Applying makes a new derived
draft with fresh check and approval requirements. Approve a clean draft even
when no findings were reported. Rules may settle recurring questions only in
their recorded scope; they never sign off an unseen output.

If the workspace revision, source bytes, rule authority, or an approved dependency
changes, reload and review the new output. Never reuse stale approvals. An
interrupted application leaves originals and a transaction journal on disk.
Run `recover` to finish only if target hashes still match the journal. External
edits cause a refusal, preserving both edits and archived originals for inspection.

For old sessions, follow [the explicit migration guide](../../specs/campaign-cycle/migration.md).

## Production execution

`catalog` lists canonical stages, prerequisite stages, mandatory checks and the
human decision for each boundary. `start` cannot remove mandatory checks or
skip approved dependencies. Its optional `options` object supplies fixed CLI
parameters; `execute` takes `run_id`. Native stages return their resolved task.
The editor Execute control invokes the same CLI through SSE; `resume` explains
the next required action. Failed or interrupted execution keeps its log and
requires a distinct retry run, preserving previous output and reviews.

Render/release selections contain exact input paths. Fixed stage options are
`input`, `gmassist`, `summary`, `session-summary`, `plan`, `recap`, `party`,
`characters`, `party-config`, `players-config`, `narration-genre-file`, `batch`,
`batch-scenes`, `narrate-tokens`, `prose-mode`, `reflections`, and `title`.
Input options must refer to explicitly selected, hash-recorded inputs.
CLI stages write under `.session-workflow/work/<run>/outputs`, so backend
comparisons are distinct runs. Explicitly select the approved version before
assembly. Never execute a Markdown skill as code.

`sd_plan --party-config config/party.yaml` uses declared characters; optional
`--characters` is an exact, nonempty subset. Player declarations stay separate
from character attribution. Optional session `player_overrides.yaml` has
`schema_version: 1` and a `speakers` map of display name to declared player ID
or null. Unresolved speakers and duplicate cues are surfaced; no character is
inferred from a player who voices several characters.

Narration writes preserve bytes and generation metadata under adjacent
`.versions/<filename>/<sha256>`. Existing narration-wiki collections now
preserve their corpus at collection time. Historical hash references resolve
those exact bytes after rerenders; existing guidance gates remain unchanged.
This is additive evidence preservation, not an upgrade of workflow or wiki state.

## Memory and prep

Save `memory-scope` with explicit campaign-relative `chapters` and `notes`
lists (the editor has matching fields). Empty notes means no notes. Empty
chapters refuses execution. `memory-plan` reports existing source-lineage
choices, source hashes, stale selection, unresolved workflow gates, event-spine
prerequisites and native tasks for the existing ensemble, dossier, event,
thread and projection tools. Historical lineage markers do not sign off a new
draft. No entity alias is inferred from a transcription garble.

A pending `memory` run requires an approved release and the persisted scope.
Native agents use the existing grounding tools against exactly that scope and
submit draft output references. `memory-events` takes `run_id`, explicit
`corpus` paths and optional `previous_store`, all already recorded as run inputs;
it calls the existing event-spine updater into the run's draft output directory.
It preserves events from unselected chapters. Its output still needs review.

Before approving a memory draft, invoke `promotion-scope` with `run_id` and a
`promotions` mapping of output path to campaign-relative destination under docs.
Targets and their previous hashes are part of the draft approval binding.
`promote` takes only `run_id`, refuses changed live targets and unapproved drafts,
preserves previous bytes, and is recoverable/idempotent. `prepare-next` consumes
the same explicitly selected notes and fresh, approved memory inputs. A guidance
change still belongs to narration-wiki's independent gates.

For an existing standalone review page export (`schemaVersion: 1`, `reviewId`,
and a decisions dictionary or array), use `import-legacy`. Supply `run_id`, the
current `draft_binding`, the original `document`, human `actor` and `rationale`,
and explicit `bindings`. Each binding names `legacy_id`, `legacy_decision`,
current `finding_id`, `finding_sha256`, and its equivalent current `decision`.
This is an explicit human validation operation; IDs are never matched by guess.
Unmarked/pending items refuse import, discussions remain unresolved, and the
original JSON and mapping are preserved as evidence. No draft approval is imported.

Approved replacements in recorded workflow outputs create a distinct derived version under the new run’s output directory. Previous drafts remain readable at their original paths. Unchanged companion reports retain their original paths and describe that earlier generation; the replacement run’s checks record the incremental verification. Resume directs review to the replacement version, which needs its own checks and explicit draft sign-off.

## Single-user review

The editor saves Approve, Reject, Discuss, and whole-draft approval with one click.
No name or rationale entry is required. Discuss remains unresolved and offers an
optional note. The CLI uses the same defaults when `actor` and `rationale` are
omitted from explicit `decide` or `approve` commands: `local user` and a standard
description of the action. These are action records, not invented explanations.
Explicit identities and notes remain supported for existing CLI callers and
validated imports. No decision or approval is inferred by loading a workspace.

Existing YAML records and historical reviewers are unchanged; there is no state
schema change or migration. Draft/source bindings, required checks, explicit
selection, and separate draft approval remain enforced.

After a fresh draft approval, **Continue with agent** shows the next stage and a
ready-to-copy **Next step for agent** prompt. Click **Copy next-step prompt** and
paste it into your agent chat. It includes the campaign configuration, exact
session directory, approved run, saved revision, and instruction to stop at human
review. For approved Events, the next stage is `remove-recap`. Copying does not
start work or change the saved workflow. Unapproved or stale runs retain the
review handoff instead. CLI users can read the same prompts in `resume` output
under `continuations`; the stage catalog supplies the next boundary.
