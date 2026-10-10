# Implementation Plan: Shared Review and Identity Adjudication

**Branch**: `codex/547-review-adjudication` | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: `specs/036-review-adjudication/spec.md` — issue #547 and children #520, #523, #522.

## Summary

Deliver one durable campaign-local review workflow, first exercised by NPC verification failures, then duplicate identities and the four grounding drafts. A dedicated private capability-URL server supplies the phone/desktop review page. CLI owns all domain behavior; the existing application launches the service and exposes local administration, application, export and recovery controls.

The user chose registry identity merges without obligatory summary edits. Summaries still govern facts, and factual correction uses #546's reviewed source workflow. Review acceptance, exact mutation approval and whole-document sign-off remain separate gates. No new automatic LLM call is introduced. Explicit ledger v2 migration adds audit-only shared review decisions; entity registry v1 is unchanged. Only persistent global merges apply; scoped requests remain visible and blocked pending #483.

## Technical Context

**Language/Version**: Python >=3.10 (existing project floor); TypeScript/Vue 3 for app integration; packaged browser JavaScript/CSS for the single dedicated viewer.

**Primary Dependencies**: Existing Pydantic 2, PyYAML 6, FastAPI, Uvicorn; existing CLI entry point and `server/subprocess_runner.py`. Python standard library hashing, secure randomness, process control and file locks. No additional production framework or database.

**Storage**: Strict JSON review snapshots/events, YAML authority ledger v2, unchanged entity registry v1, immutable proposal/receipt snapshots, shared authority journals, versioned dependency manifests. Files are truth; runtime process handles are private/disposable.

**Testing**: Pytest domain/CLI/real-process integration, existing frontend build and Playwright, installed-wheel resource smoke, crash failpoints, security boundary tests, and recorded real-phone walkthrough.

**Target Platform**: Existing Linux/POSIX campaign host with flock semantics, modern desktop/mobile browsers, explicit private LAN or Tailscale reachability. Local filesystem with durable atomic file replacement; no claim of multi-file filesystem atomicity or unverified network-filesystem lock guarantees.

**Project Type**: CLI pipeline with private web review service and existing application launcher.

**Performance Goals**: Review 25 NPC findings, 38 duplicate pairs and four long documents without page overflow or lost acknowledged decisions. Paginate 50 items per request; typical local save target <=1 second excluding network transit. Bounded subprocess failures surface within configured deadlines. These are acceptance/design targets, not measured results.

**Constraints**: Explicit selection; human scope/identity decisions; no source edits on review save; summary/VTT boundaries; capability-only remote read/save; no broad application exposure; private scope chosen by user; preserve CLI/UI parity; exact-input proposals; crash recovery; new state versions migrate deliberately.

**Scale/Scope**: Single GM/campaign with concurrent devices; no multi-tenant account service. Deliver #520/#523/#522 and grounding document integration. #483 receives a documented dependency/refusal boundary; #519/#535 and narration-wide review migration are excluded.

## Constitution Check

Pre-research evaluation found no unjustified violation. Post-design evaluation below covers all thirteen principles against the final contracts. PASS means the design satisfies the principle; implementation tests remain required.

| Principle | Before research | Post-design evidence / gate |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | Pass | Immutable review files, authority history, no browser-only truth; generated prose needs sign-off. |
| II. The Human Checkpoint is Non-Negotiable | Pass | Exact decisions, scope/canonical choice, source/apply preview and document sign-off; no automatic semantic adjudication. |
| III. Retrieval and Render are Separated | Pass | Review operates on prepared evidence; existing extraction/render seams retained; no new model pass. Run isolation regression. |
| IV. Verbatim is Sacred | Pass | No VTT mutation; exactness blockers cannot be waived; factual summary change uses #546 adapter. |
| V. One Seam per Boundary | Pass | CLI domain owns review; bounded subprocess is the HTTP invocation seam; no new model/provider integration. |
| VI. CLI is the Engine, UI is a Face | Pass | Dedicated and main-app adapters invoke CLI; no registry/decision mutation implemented in routes. |
| VII. Extract Once, Synthesize Deliberately | Pass | Item-scoped verification, deterministic dependency rebuilds and reuse of unchanged extraction caches; no merged synthesis pass. |
| VIII. State is Discoverable | Pass | Status/history/manifests expose pending, stale, blocked, recovery and apply state; migration/quickstart document seams. |
| IX. The UI Mechanizes; Claude Converses | Pass | Same files/decisions in CLI, chat and phone; Discuss retains notes and remains unresolved; no UI-only gate. |
| X. Selection is Explicit; There Is No Silent All | Pass | Materialized source/item selections; empty batches refuse; rerun previews bind exact item revisions. |
| XI. Parity is Bidirectional | Pass | Every command has local application controls; dedicated review page is shared, admin/apply stay on trusted local control surface. No CLI-only exemption. |
| XII. One Spelling per Option | Pass | Shared ReviewConfig and existing --config/--campaign-dir/--json meanings; --force never bypasses approval/freshness. |
| XIII. Breaking State Changes Migrate Out of Band | Pass | Explicit authority/manifest migration, immutable old evidence, live old-version refusal, operator guide; no silent fallback. |

The user explicitly selected the dedicated service and merge policy. No constitutional exception is requested. Security review of the new network surface is a release gate, defined in [HTTP/security contract](contracts/http-security.md). Pending runtime proof is not a reason to claim a design violation or completed testing.

## Project Structure

### Documentation (this feature)

```text
specs/036-review-adjudication/
  spec.md
  plan.md
  research.md
  data-model.md
  migration.md
  quickstart.md
  evidence.md
  checklists/requirements.md
  contracts/cli.md
  contracts/http-security.md
  contracts/verification.md
  contracts/identity-apply.md
```

`tasks.md` is generated by the next `$speckit-tasks` phase; this plan does not create it.

### Source Code (repository root)

Proposed new files/subpackages unless marked existing:

```text
pipelines/summary_native/review/
  models.py           # strict items/events/selections/proposals
  store.py            # durable review operations under shared campaign lock
  cli.py              # subcommands and stable JSON envelopes
  verification.py     # NPC queue producer + selected-check reruns
  identity.py         # pure merge proposal, closure, apply integration
  documents.py        # draft review/sign-off/reviewed-bundle promotion
  access.py           # grant validation, lifecycle metadata
  service.py          # CLI-owned managed process start/status/stop
  web/app.py          # protected transport adapter, subprocess dispatch
  web/viewer.html
  web/viewer.js
  web/viewer.css
  migrate.py
campaignlib/review_config.py
server/routers/review_routes.py
frontend/src/components/ReviewLauncher.vue
frontend/e2e/summary-native-review.spec.ts
docs/cli/summary_native_review.md
tests/test_summary_native_review_*.py
tests/fixtures/summary_native_review/
```

Existing integration points: `pipelines/summary_native/cli.py`, `npc_verify.py`, `npc_publish.py`, `duplicates.py`, `corpus.py`, `freshness.py`, `authority.py`, `authority_apply.py`, `authority_inputs.py`; `campaignlib/registry.py` and its direct consumers; `server/subprocess_runner.py`, router registration, `frontend/src/views/grounding/SummaryNative.vue` and NPC dossier controls. Frontend component placement may follow repository conventions during tasks, but domain/interface contracts are fixed by this plan.

**Structure Decision**: Keep the reusable review domain next to summary-native; package its dedicated viewer in the Python wheel. Reuse the installed console command and bounded process seam. The existing narration reviewer keeps its purpose; no summary-native logic is added to its unauthenticated handler. Extract reusable registry/transaction primitives where needed, never duplicate competing state stores.

## Phase 0 — Research Results

All planning unknowns are resolved in [research.md](research.md): existing review transport, state durability, item continuity, semantic taxonomy, shared ruling extension, recoverable mutation, document promotion and scope compatibility. Codememory discovery was cross-checked against the worktree because the index points at the older original checkout; direct reads of newly merged #546 code supplied missing index coverage.

The setup script returned feature identifier `036-review-adjudication` in its BRANCH field; actual git branch remains `codex/547-review-adjudication`. The feature pointer, not a branch rename, selects this directory.

## Phase 1 — Design and Delivery Order

1. Introduce strict review records and authority v2 migration, shared journal capabilities and tests; immediately exercise them with the NPC queue producer. This is the first end-to-end slice, not a standalone speculative platform.
2. Add capability service, safe renderer, phone save/resume and app/CLI parity around that real queue. Demonstrate lost-response retry, competing devices, restart, stale input and human semantic finding entry.
3. Refactor verifier checks for precise reruns and preserve diagnostics; protect publication from mechanical failures and absent document sign-off.
4. Add duplicate identity proposals, complete dependent-artifact preview and persistent/global merge application. Introduce per-subject dependency manifests/migration, shared registry read/write locking and safe scoped refusal. Shared distinct decisions suppress only their valid evidence/scope.
5. Add long-document review/sign-off/export and narrow reviewed-bundle promotion, retaining existing outline/pointer/freshness checks.
6. Finish operator/migration docs, package checks, security review and real-phone acceptance. No live campaign migration, service publication or data mutation occurs during planning.

### Important integration obligations

- Registry v1 lacks UUID identities and per-alias scope. Keep review-local stable subject IDs plus immutable registry snapshots; historical loser names must remain valid audit references after a merge.
- Audit-only review decisions cannot enter planning context or conflict precedence as if they were factual source rulings. Update every authority record reader and test #546 behavior after migration.
- Shared ledger-wide revision changes should not stale unrelated item approvals; item freshness is dependency-based. Exact source proposals still bind full input/ledger state and may need refresh.
- Source and identity mutations share one recoverable locking boundary. Legacy registry writers must participate so a direct command cannot race a reviewed proposal. No model call holds the writer lock.
- Scoped requests are stored but not applied. `distinct` decisions stay in the shared review ledger; registry v1 cannot express their scope/evidence ownership.
- A wrong generated claim with correct source must not produce an unnecessary summary change. It is a draft correction/regeneration problem with its own reviewed disposition.

## Verification Strategy

- Strict schema/state tests, decision compare-and-swap, retry IDs, exact evidence/rule freshness, unrelated changes, same-text different-subject/occurrence and audited rebind.
- All seven categories, original legacy diagnostics, false-entailment and typography fixtures; instrument check execution to prove only selected checks ran.
- Durable real CLI/server integration with disconnect/restart, simultaneous devices and grant revocation races. Every transport command compared with CLI envelope/result.
- Full affected-dependency merge preview and staging; type/scope/anti-merge/path collisions; create/replace/delete crash matrix and unexpected-byte recovery refusal; all consumer regression seams in R9.
- Authority v1→v2 and dependency-manifest migration tests including pending transactions, unknown fields, old source-proposal freshness, immutable history and repeated execution.
- Existing summary-native, authority, registry, provenance identity and retrieval/render regressions; installed-wheel asset smoke; frontend build; Playwright at 320/375 pixels; real-phone recorded acceptance.
- Security adversarial suite and written implementation review against the dedicated server contract. Do not call the feature released solely on unit tests or a mocked mobile viewport.

## Complexity Tracking

No constitutional violations or exceptions. The user-requested private server adds one managed process and one security boundary; strict route scope, reuse of existing dependencies and one adjudication viewer bound that cost. The authority schema and transaction upgrades are required for durable shared rulings and safe multi-file identity application.
