# Implementation Plan: Reviewed Bundle Promotion Gate

**Branch**: `codex/548-promotion-gate` | **Date**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Input**: `specs/037-promotion-gate/spec.md`, issues #548/#521/#517, baseline `5e63e85`.

## Summary

Publish the four reviewed grounding documents with their timeline and complete references as one accountable generation. Reuse #546 authority and #547 review decisions. Deliver the promotion foundation first, then attach a deterministic cross-document gate sized from the five-example Phandalin spike. Semantic extraction remains candidate work that the GM must review.

Astra owns this design; GPT-5.6-Sol researches integration and will orchestrate/code after task generation and implementation are requested. Planning changes documentation only.

## Technical Context

**Language/Version**: Python >=3.10; existing TypeScript/Vue 3 frontend. Preserve the repository Python 3.10/3.14 installable-wheel gates.

**Primary Dependencies**: Existing Pydantic 2, PyYAML, FastAPI, subprocess execution seam, Vue/Pinia, pytest and Playwright. No new database or production service.

**Storage**: Campaign-local Markdown/YAML source authority, strict versioned JSON manifests/reports/receipts, and existing review events. Publication storage and crash protocol are specified in the design artifacts below.

**Testing**: Focused pytest integration and process-interruption tests; existing authority/review/reader regressions; installed-wheel smoke; Vue production build; Playwright plus phone review acceptance.

**Target Platform**: Current Linux/POSIX campaign host on a local filesystem with working advisory locks, atomic same-filesystem rename, and file/directory synchronization. Reject unsupported mounts before mutation; no NFS or multi-host coordination guarantee.

**Project Type**: Installed CLI engine with an existing web application and private shared review service.

**Performance Goals**: No model calls during dry-run, checking accepted structured claims, or publication. Read each selected input once per stable snapshot where possible; compare structured claims by indexed subject/key/scope rather than unrestricted all-pairs prose comparison. Bound model extraction by explicit selected chunks and configured token limits. Correctness/freshness precede latency; UI reports progress without optimistic success.

**Constraints**: Exact all-four selection, full reference membership, unchanged source wording on promotion, no automatic commit/push, current whole-document sign-offs, human-only semantic decisions, durable receipts and previous generation retention, same-feature UI parity, explicit migration if live layout changes.

**Scale/Scope**: One campaign/range per operation; exactly four grounding outputs plus timeline and arbitrary nested generated references. Acceptance includes a ~200 KB long document, changed and removed references, competing promotions, and all five Phandalin failure shapes with positive controls. Multi-campaign transactions and public sharing are excluded.

## Constitution Check

Initial and post-design review passed all thirteen constraints. Implementation evidence in `validation.md`, `security-review.md`, the parity/browser suites, and the installed-wheel matrix verifies the same obligations. No constitutional exception is requested.

| Principle | Initial gate | Post-design requirement |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | Pass | Files carry all manifests, claims, review history and receipts; candidates are never authority. |
| II. The Human Checkpoint is Non-Negotiable | Pass | GM reviews exact extracted claim meanings, disputes and all four documents; publication is explicit. |
| III. Retrieval and Render are Separated | Pass | Source selection/snapshot and model extraction are separate functions; no model call in promotion/checker. |
| IV. Verbatim is Sacred | Pass | Keep exact quoted evidence and source locators; promotion copies reviewed bytes without rewriting. |
| V. One Seam per Boundary | Pass | Optional extraction uses campaignlib's existing model seam; application invokes installed CLI. |
| VI. CLI is the Engine, UI is a Face | Pass | Domain behavior belongs to CLI library, with typed subprocess adapters. |
| VII. Extract Once, Synthesize Deliberately | Pass | Extraction caches exact selected input/rule/model bindings; no synthesis redesign or unchecked call chaining. |
| VIII. State is Discoverable | Pass | Status exposes old/new generation, review gaps, failed checks and recovery work from disk. |
| IX. The UI Mechanizes; Claude Converses | Pass | Application invokes, shows and links to shared review; facts and rulings remain human decisions. |
| X. Selection is Explicit; There is No Silent All | Pass | Explicit range and exact source/chunk selection; empty selection refuses. |
| XI. Parity is Bidirectional; Every CLI Capability Has a Face | Pass | Preview, checking, extraction, review, migration, publish/status/recovery all have application controls. |
| XII. One Spelling per Option; No Configuration Drift Across CLIs | Pass | Reuse --config, --since/--until/--out-root, --backend/--model, --force semantics; migrator uses --campaign-dir. |
| XIII. Breaking State Changes Migrate Out of Band and Ship a Migration Document | Pass | Separate deliberate migration, dry-run/bound apply, legacy refusal, operator documentation; no lazy upgrade. |

## Project Structure

### Documentation (this feature)

```text
specs/037-promotion-gate/
├── spec.md
├── discovery.md
├── spike.md
├── plan.md
├── research.md
├── data-model.md
├── migration.md
├── quickstart.md
├── contracts/
│   ├── cli-ui.md
│   ├── publication.md
│   └── claims.md
└── checklists/requirements.md
```

`tasks.md` is the implementation ledger; completion evidence is recorded in `validation.md`.

### Source Code (repository root)

```text
campaignlib/
  grounding_bundle.py            # shared bundle snapshot/path/lock boundary
  config.py                      # multi-document assembly uses one bundle snapshot
  grounding_config.py            # centralized promotion/claim settings
pipelines/summary_native/
  promotion/                     # manifest, gates, publication, status/recovery
  claims/                        # selection, normalization, pure checks, report/review adapter
    extract.py                   # separately invoked model seam; never imported by pure gate
  cli.py                         # explicit command dispatch before mutating scan pipeline
  review/documents.py            # stronger sign-off bindings; retire publication bypass
  review/cli.py                  # preserve existing review commands and refusals
server/
  migrate_grounding_bundle.py    # explicit one-shot workspace adoption/migration
  routers/summary_native.py      # typed invocation/status endpoints
  routers/review_routes.py       # existing review handoff/legacy refusal
frontend/src/
  views/grounding/SummaryNative.vue         # bundle selection, preview, checks, publication/status
  components/ReviewLauncher.vue # existing shared-review invocation
pipelines/rlm/mcp_server.py       # grounding reads through shared snapshot boundary
pipelines/session_prep/prep.py    # coherent context snapshot
session_doc/                     # affected grounding readers use shared snapshot
tests/                          # promotion, claims, migration, reader regressions
frontend/e2e/                   # application + shared review acceptance
```

**Structure Decision**: Extend the existing package and review subsystem. The storage reader belongs in campaignlib because multiple pipelines consume live grounding documents. Exact affected readers/writers and integration rules are recorded in research and the publication contract. No second review application.

## Complexity Tracking

No constitutional violations. A bundle manifest, a consistent reader boundary, and crash recovery are required by #521; existing per-file replacement alone cannot satisfy its publication guarantee. The completed spike and the user’s reconstruction ruling justify the separately selected candidate extractor; its output is never a verdict.

## Phase 0 Outcome

[research.md](research.md) resolves the technical choices and [spike.md](spike.md) records all five original evidence inventories. On 2026-10-10 the user explicitly authorized labeled reconstructed fixtures where the original faulty bundle is unavailable. No unresolved planning clarification remains. Historical replay remains unverified and is not a promised acceptance result.

## Phase 1 Design

- [data-model.md](data-model.md): strict bundle, source/claim/report, review binding, preview, generation, activation and migration records; acyclic digest dependencies.
- [contracts/publication.md](contracts/publication.md): one pointer activation, exact retained bytes, coherent readers, manual edit policy, durable activation evidence and failure/recovery outcomes.
- [contracts/claims.md](contracts/claims.md): reviewed mapping versus source truth, six rule families, shared-review dispositions, coverage limits and reconstructed evidence.
- [contracts/cli-ui.md](contracts/cli-ui.md): exact command/route/control parity, explicit selections, pure preview, idempotent commit and separate migrator.
- [migration.md](migration.md): deliberate workspace adoption, preserved compatibility paths, pending-state reader refusal and operator verification.
- [quickstart.md](quickstart.md): disposable end-to-end validation and required automated/phone evidence.

### Delivery sequence for task generation

1. Build strict manifest/snapshot models and pure full-bundle preview. Audit affected reader/writer entry points and the actual generated timeline/path-record layout.
2. Implement the explicit migrator and application invocation with recovery, retained originals and pristine/legacy baseline distinctions. Introduce shared snapshot readers and managed-target writer refusals together.
3. Implement generation staging, copied-output pointer/outline checks, activation receipts/history, status/recovery, no-op/replay behavior and fault/concurrency tests. Close legacy per-document publication bypasses. This is #521’s independently testable foundation; report claims checking as unavailable until stage 5, never silently passed.
4. Implement selected source packets and explicit candidate import/extraction with caching and the shared GM mapping review. Add the reconstructed five-case fixtures with provenance and positive controls. Do not auto-write facts from the spike into a live campaign.
5. Implement pure structured claim comparisons, candidate findings, resolution review and v2 whole-document sign-off context. Integrate this into the publication gate, preserving the acyclic digest order and relevant dependency freshness.
6. Complete main application controls, private phone review regression/acceptance, migration/operator documentation and installed-wheel/broad shared-seam gates. All new CLI choices must be reachable from the application before feature completion.

The implemented task sequence follows these stages; deviations and validation evidence are recorded in `tasks.md` and `validation.md`.

### Validation and release gates

- Pure dry-run: filesystem membership and content unchanged, no model calls and no implicit lock/config initialization.
- Atomic publication: cooperating multi-document readers observe a complete old/new snapshot; process faults at every boundary distinguish precommit failure from unknown acknowledgment after activation; previous exact live bytes and unrelated files remain intact.
- Authority and review: selected source/meaning/identity/audience/rule changes stale the affected approval; destination-only changes stale preview; missing sign-off, candidate, check or evidence cannot silently pass.
- Semantic honesty: six finding categories, all five reconstructed negatives and positives, explicit human-normalization provenance; no latest-wins or citation-entailment shortcut.
- Parity/migration: package-installed CLI, typed application routes, responsive shared review, deliberate migration and unsupported old-state refusals. No new public network authority.
- Required existing no-model guards, source-no-live-write tests, retrieval/render isolation, Python wheel matrices and relevant config/reader/review regressions pass.

### Final Constitution Gate

**PASS (implementation review)** for all thirteen principles. Deterministic architecture guards, installed CLI/route parity, explicit selection and review records, deliberate migration, durable recovery tests, owner-only candidate evidence, and the application/private-review acceptance preserve the design gates. No exception, CLI-only waiver, silent state migration, new fact authority, or automatic model verdict is introduced. Filesystem guarantees apply to the stated local platform and cooperating repository consumers; external concurrent edits and physical storage corruption are not silently covered.

### Known limits and risks

- The original faulty four-document Phandalin generation was not recovered; fixtures reconstruct the reported failure shapes under explicit user authorization.
- Atomic visibility depends on integrating every repository bundle reader. A missed direct-path reader is a release defect, not a deferred improvement.
- Human edits are supported at managed regular-file paths; temp-rename saves over compatibility aliases detach them and must be reported without discarding either copy.
- A synchronized pointer switch and activation-history reconciliation are distinct steps. A lost response must remain inspectable as committed/unknown, never reported as a safe rollback without evidence.
- Partial legacy bundles or unclear ownership may require operator repair before migration; the tool refuses rather than guessing.
