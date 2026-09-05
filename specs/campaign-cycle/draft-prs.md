# Prepared draft PR descriptions

The user explicitly approved publication after the initial automatic approval-review rejection. All six code PRs below are published as drafts. Campaign pilot artifacts remain local, and pilot human approvals remain pending.

| Component | Draft PR | Base | Head |
| --- | --- | --- | --- |
| Records | [CampaignGenerator#378](https://github.com/kostadis/CampaignGenerator/pull/378) | `main` | `feat/cycle-records` |
| Review | [CampaignGenerator#379](https://github.com/kostadis/CampaignGenerator/pull/379) | `feat/cycle-records` | `feat/cycle-review` |
| Orchestration | [CampaignGenerator#380](https://github.com/kostadis/CampaignGenerator/pull/380) | `feat/cycle-review` | `feat/cycle-orchestration` |
| Memory | [CampaignGenerator#381](https://github.com/kostadis/CampaignGenerator/pull/381) | `feat/cycle-orchestration` | `feat/cycle-memory` |
| Integration | [CampaignGenerator#382](https://github.com/kostadis/CampaignGenerator/pull/382) | `main` | `feat/cycle-integration` |
| Skills | [mytools#151](https://github.com/kostadis/mytools/pull/151) | `main` | `feat/cycle-skills` |

## records

Base: `main`. Head: `feat/cycle-records`. Draft.

Session production previously had no shared, versioned record binding stage inputs, outputs, reviews and approvals. This adds strict YAML contracts, exact-byte evidence snapshots, revision checks and journaled recovery behind the existing atomic-write seam. It exposes no unfinished public operation.

Validation: 198 records, atomic-write and retrieval-isolation checks passed. Part of the campaign-cycle integration; no issue is closed solely by this infrastructure milestone.

## review

Base: `feat/cycle-records`. Head: `feat/cycle-review`. Draft.

Review progress can now persist beside session artifacts and survive editor, CLI and agent handoffs. Adds the session_workflow engine, FastAPI command adapter, editor decision controls, hash-bound Approve/Reject/Discuss records, separate human draft approval, approved application and explicit migration/import contracts.

A clean automated audit never approves a draft. Unmarked findings remain unresolved. Applying changes produces a derived draft needing fresh review.

Validation: 214 workflow and constitutional checks passed; Vue production build passed. Stacked on cycle-records. Final integration also adds real standalone-page import validation and browser/API acceptance coverage.

## orchestration

Base: `feat/cycle-review`. Head: `feat/cycle-orchestration`. Draft.

Session stages now enforce approved prerequisites and mandatory checks, expose native-agent tasks with resolved inputs, and execute existing CLIs into distinct run directories. Resume reports stale, failed and pending work. Planning supports declared-roster subsets, transcript identity keeps players separate from characters, and narration bytes/settings survive replacement and remain available to historical wiki evidence.

Validation: 275 workflow, planning, narration, wiki, batching and retrieval-isolation checks passed; frontend build passed. Stacked on cycle-review. Final integration strengthens partial-scene and metadata forwarding.

## memory

Base: `feat/cycle-orchestration`. Head: `feat/cycle-memory`. Draft.

Adds persisted, explicit chapter/note selection and memory handoffs using existing lineage, ensemble, event, thread and projection mechanisms. Event-spine updates accept an explicit corpus. Grounding promotion binds approved draft bytes to selected destinations and previous hashes, preserves originals and refuses stale application.

Validation: 253 workflow, memory, lineage, chapter-identity and retrieval checks passed; frontend build passed. Stacked on cycle-orchestration. Production promotion remains gated on human review.

## integration

Base: `main`. Head: `feat/cycle-integration`. Draft.

CampaignGenerator now owns versioned session progress, preserved evidence, shared review decisions, production gates and selected memory handoffs. The editor invokes the same CLI engine as chat/native agents. Source changes invalidate downstream approvals; clean audits cannot approve drafts; application and promotion preserve originals and reject stale decisions.

Assembles records, review, orchestration and memory components, plus exact partial-scene execution, resolved generation metadata, validated standalone-review imports and browser/API acceptance. Operator and migration instructions are included under docs/cli/session_workflow.md and specs/campaign-cycle/.

Validation: 4,729 regression tests passed, 199 skipped, with 29 independently reproduced baseline failures excluded (the exact list is committed). Final affected checks, production frontend build, real API-to-CLI test and Chromium approval/reload/CLI handoff passed. The complete unfiltered suite is not green; the existing failures remain visible.

Rollout remains incomplete: Phandalin and obelisk capture pilots preserved source bytes and proved a clean audit cannot advance without human approval. Both await explicit review; subsequent production, backend comparisons, release and refreshed prep acceptance are pending. Obelisk also needs a genre rulebook selected before rendering. No campaign documents were published or historical approvals inferred.

Shared adapters: kostadis/mytools commit 8801387bb00edecc6b3d08ae8d18df01cd132dc3. Exact local campaign acceptance commits and measurements are recorded in specs/campaign-cycle/acceptance.md. Keep this PR in draft until the pilot gates and acceptance criteria are completed. No blanket migration or issue closure is claimed.

## skills

Base: `main`. Head: `feat/cycle-skills`. Draft.

Claude and Codex specialist entrypoints now share the campaign-cycle v1 contract for disk state, source hashes, task scope, output submission and human review. Existing standalone specialist instructions are retained as references. Managed workflows submit to CampaignGenerator instead of creating independent approval state.

Includes scene-extract, remove-recap, no-mech, scrub, voice-critic, consistency-check, staged-consistency, session-summary-consistency, voice-smooth and vtt-spell-pass for both agents. All 20 entrypoints validate and shared links resolve. Live skill installations remain unchanged.

Acceptance counterpart: CampaignGenerator implementation commit 36041d9b0bb81fca01bf5fe8bfc2c3270ed7e543. Campaign pilots are local and stop at the first human review gate.
