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
