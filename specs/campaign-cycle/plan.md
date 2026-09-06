# Campaign production integration

Baseline: `a908177` (`main`). The API-key-gate and review-findings branches
are ancestors of this baseline. Existing primary checkouts are preserved.

Implement and integrate records → shared review (CLI and editor together) →
orchestration → memory handoff. Native agents receive bounded tasks and submit
artifacts; no Markdown job interpreter or new model client is introduced.
Pilot in separate Phandalin and obelisk worktrees. Human approval of actual
pilot drafts is required before local release; a passing test is not approval.

## Constitution Check

Constitution v1.3.0 applies without a full Spec Kit workflow.

| Principle | Implementation and verification obligation |
|---|---|
| I Disk is Truth | Strict versioned session YAML, immutable evidence; reconstruct after reload. |
| II Human Checkpoint | Separate completion, checks, decisions, and hash-bound draft approval. No new model calls; existing calls propose the stage's named human decision. |
| III Retrieval/Render | Retain retrieval isolation guardrail; approved scope before render. |
| IV Verbatim | Preserve source bytes; corrections and voice smoothing explicitly derived. |
| V One Seam | Reuse campaignlib API/config/util, existing grounding tools, and subprocess runner. |
| VI CLI Engine | Session workflow engine owns behavior; FastAPI builds CLI commands. |
| VII Extract Once | Track input hashes, distinct runs and exact selected versions; reuse existing batch machinery. |
| VIII Discoverable State | Persist native-agent tasks, failures, dependencies, approvals, and recovery journals. |
| IX UI/Conversation | User's shared-editor-review choice is a narrow exception permitting explicit human decision controls. Identical CLI/chat decisions persist to the same files. No automated judgment. |
| X Explicit Selection | Empty scenes, findings, chapters, or notes never imply all. |
| XI Bidirectional Parity | Every public workflow operation and parameter is invocable and inspectable in editor. Records milestone remains internal. |
| XII One Spelling | Reuse --config, --backend, --model, --effort, --force, --campaign-dir; request schema owns workflow defaults. |
| XIII Migration | Separate dry-run migrator, exact refusal command, original-byte preservation, unknown-field reporting and migration tests. |

Reassess before each component merge. Do not change the constitution.

## Interfaces

`session_workflow.yaml` is the authoritative schema-v1 record beside artifacts;
`.session-workflow/objects/<sha256>` preserves exact bytes and `.session-workflow/`
holds recovery receipts. JSON is interchange, never an alternate authority.
Strict contracts reject unknown fields. Mutations take an expected revision,
hold a session file lock, and atomically replace YAML. Hash-bound findings include
evidence location, proposed action, and consequences for Approve/Reject/Discuss.
Unmarked and Discuss findings block approval. A clean audit still requires a
separate, named, explicit human approval of the generated output binding.

Inputs reference existing configuration, player declarations and lineage. Each
run records resolved inputs, explicit selection, dependencies, effective
generation settings, check coverage, and output snapshots. Native-agent work is
a pending task with these resolved references. Historical runs are retained.
Approved application checks source bytes again; repeated applications are
idempotent. An interrupted multi-file replacement has a durable journal and
all previous bytes; resume refuses external modifications rather than guessing.

## Verification and rollout

Use each checkout's editable environment and frontend dependencies, assert the
campaignlib import location. Test strict contracts, recovery at replacement
failure, stale decisions and dependency invalidation, clean-audit gates,
explicit selection, migration non-mutation, API command parity, browser reload,
retrieval isolation and relevant existing family guardrails. Pilot configs and
all generated files stay in isolated campaign worktrees; record repository and
adapter commits, manual handoffs and available usage in acceptance evidence.

The 59-issue allocation and explicit deferrals in the user-approved delivery
plan remain governing scope; do not infer issue closure from infrastructure.
TODO integration maps the editor stepper to persistent run state, review flows
to shared gates, incremental synthesis to selected changed chapters and cached
extractions, and batch controls to existing batch capabilities. Historical
work (scrub removal, batch extraction, scene resolver, lineage and projections)
must be reused and verified rather than reimplemented.

## Component check: shared review

Records: 198 checks passed, including import provenance, recovery and retrieval
isolation. Review: 15 records/review/migration/parity tests pass and the Vue
type-check/production build passes. No model calls added. CLI and editor ship
together; per-item decisions and draft approval are distinct. Migration refuses
unknown state and preserves original bytes. All thirteen principles reassessed
against the table above; IX remains the explicit shared-review exception.

## Component check: orchestration

275 tests pass, including the new identity, mandatory-stage, resume and narration
version tests and existing planning, narration, batching and retrieval guardrails.
Frontend build passes. Existing CLI engines perform rendering; each stage names
its human decision and enforces approved prerequisite runs. Native work remains
a persisted task. Generation, automated checks and human approval are distinct.
Prior narration and sidecar bytes survive replacement and wiki evidence resolves
the preserved hash. This additive archive does not retire a state location.
All thirteen principles reassessed; shared-editor exception remains narrow.

## Component check: memory

253 tests pass for workflow storage/review/orchestration/memory, existing lineage
and chapter identity, and retrieval isolation. Frontend build passes. Memory
scope is explicit and persisted; event-spine uses its existing incremental
updater. Promotion targets and previous hashes are included in the approved
binding, writes preserve originals and refuse changed destinations. Existing
ensemble/thread/projection mechanisms remain the native handoff tools.
No new model client or automatic guidance promotion. All thirteen principles
reassessed; empty note scope never expands and human gates remain explicit.

## Integration reassessment

Existing standalone review JSON is admitted only through explicit validated
legacy/current finding bindings. Final integration adds partial-scene execution
through the existing resolver, adjacent transition evidence, frozen backend
effort defaults, and CLI-resolved narration metadata. The editor reaches every
operation through the shared command schema. The real FastAPI/CLI route and
Chromium review/reload/CLI handoff tests pass. No human pilot signature was
inferred. The two capture pilots stop at explicit human approval, as required
by Principles I and II. Broader production acceptance remains pending.

Fresh environments require MCP v1 (the existing FastMCP seam), PDF/NumPy/OpenAI
test extras, and the existing local dgxlib dependency for DGX tests. The core
MCP dependency is bounded below v2 so a fresh editable install remains usable.
All worktrees have their own editable environment and frontend dependencies.


### Pilot correction: managed draft application

Approved findings targeting a recorded derived output under a workflow run now publish a distinct output under the revision run. Existing draft bytes remain available. Transcript originals and other workflow internals remain forbidden replacement targets. CLI and editor continue to invoke the same application engine and request contract.

Constitution Check: all thirteen obligations above still hold. In particular I/II/IV retain originals and require fresh checks plus separate human approval; VI/XI share the existing CLI/editor operation; X applies only individually approved selected findings. No model calls, options, schema changes, or migration are introduced. Regression coverage verifies two fixes to one transcript, preserved prior bytes, idempotent replay, original/internal target refusal, and an unapproved corrected draft after a clean check.

Resume retains revised drafts as history and directs pending review only to their replacement. The same regression verifies this handoff.

Events/extraction pilot preflight: the existing `party` option now reaches both fixed CLI commands, enabling their roster-backed wrong-transcript check. Constitution Check: existing selection and human gates remain; one CLI engine gives editor parity, no new schema/options/model boundary. A parameterized command test covers both consumers and rejects unselected party context.


### Pilot review controls and conversation handoff

The editor puts Approve, Reject, and Discuss on every finding. Reviewer identity appears before the cards; Discuss records a specific note through the existing `decide` request. Saved decisions remain visible after reload. Checkboxes are explicitly bulk selection, and whole-draft sign-off is separate. A copyable handoff identifies the saved run and notes for native agent continuation; it does not claim to launch or message an agent.

Constitution Check: I/II retain disk authority, source-bound decisions, and independent draft approval; VI/XI reuse the same CLI request and server boundary; IX stays within the user’s explicit shared-editor exception and preserves chat discussion; X materializes each chosen finding. No new backend, schema, option, or migration is introduced; remaining principles are unchanged. Browser tests exercise all three decisions, discussion notes across reload/CLI export, source-change refusal, no implicit application/approval, and desktop/narrow layouts.

The follow-up reviewer-name fix keeps all three per-finding choices available. Missing identity opens a local name prompt before saving, and a saved Discuss remains changeable to Approve/Reject. Identity is still supplied by the human, not inferred from an earlier reviewer. Constitution Check: unchanged CLI contract, source hashes, per-item decisions and separate draft approval; no schema or migration. Browser coverage includes blank-name approval and Discuss → Approve after reload.

### Pilot correction: single-user review

The user explicitly requested one-click review without reviewer-name or rationale
prompts. The CLI engine now supplies `local user` and a standard action description
only for explicit review mutations with omitted fields. The editor uses those
same defaults, including draft sign-off, and offers optional discussion notes.
Explicit CLI identities and notes, strict disk contracts, and old history remain.

Constitution Check: all thirteen obligations above still hold. I/II preserve
source-bound explicit human clicks and the independent draft gate; VI/XI/XII
share defaults in the CLI engine and expose the same behavior in the editor;
VIII/IX retain saved discussions and native-agent handoffs; X retains explicit
finding selection. III/IV/V/VII add no retrieval, source edits, generation, or
external seam. XIII needs no migration: disk schema and legacy records are
unchanged; only optional command inputs gain defaults. Verification covers
one-click decisions, optional discussion, reload, CLI parity, stale refusals,
and unchanged clean-audit and unresolved-finding gates.

### Pilot correction: next-stage agent prompt

Fresh approved runs expose a copyable continuation prompt naming the next stage,
campaign, session, run and revision. Existing `resume` generates the prompt from
the canonical stage catalog; the editor displays that same text. It directs the
agent to reload disk state, resume existing work, ask about missing scope, and
stop at human review. Stale and unapproved runs do not get a next-stage prompt.

Constitution Check: all thirteen obligations still hold. I/II/VIII preserve disk
authority and separate approval gates; VI/XI reuse the CLI resume boundary with
matching UI output; IX keeps native work in chat; X prohibits guessed scope.
No stage executes on copy, no new model/retrieval seam or options are added, and
no on-disk shape changes (XIII). Tests cover fresh approval, stale suppression,
read-only prompt generation, and editor/CLI handoff.


## Voice-smooth calibration review (2026-09-06)

Close the pending-native-task UI gap by explicitly registering a preserved sample
and grouped original/smoothed cards in the existing run. Save individual decisions
and a separate calibration approval before remaining scenes are rendered. Keep
full draft submission, checks, and sign-off separate. Implement engine contracts,
editor controls, reload/staleness/gate tests, then register the isolated pilot.

### Constitution Check

I, IV, VIII: YAML workflow owns decisions; original extraction and immutable sample
bytes remain available. II: calibration is a human gate before further rendering,
never approval of unseen output. III, V, VII: no retrieval changes, new model calls,
clients, or extraction reruns. VI, XI: the existing subprocess command boundary
exposes every new calibration operation in CLI and editor together. IX: the
previously approved narrow shared-editor-review exception applies; chat handoff
and JSON interchange remain equivalent. X: cards reference only selected inputs;
bulk choice materializes IDs; complete submission covers selected scene filenames.
XII: reuse existing command flags and single-user defaults. XIII: no existing state
is rewritten on read; optional versioned task metadata is explicitly registered.
Provisional calibration files remain historical evidence; registration does not
import decisions or approval. See migration.md and the operator guide.

Validation: focused workflow contracts, reload/CLI browser handoff, mobile layout,
existing review/orchestration/option parity and retrieval/render isolation tests.
