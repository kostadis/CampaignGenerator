# Implementation Plan: Incremental Campaign Grounding and NPC Updates

**Branch**: `039-incremental-campaign-updates` (name reserved; not yet checked out. Implementation goes on this branch as a PR, never directly on `main`) | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/039-incremental-campaign-updates/spec.md`

## Summary

After a session is reviewed, the GM updates the four grounding documents and the affected NPC dossiers from the last *published* baseline plus only the newly selected chapters. The existing native gates (authority, verification, review, freshness, promotion, publication) stay in place. The feature adds the missing lineage: an explicit selected-source set, a bound baseline for each document and each NPC, typed full-versus-sparse evidence, host-applied minimal edits, a per-item dependency graph, unchanged attestations, and a durable run that can be stopped and resumed.

Technical approach (from research.md): a new `pipelines/summary_native/delta/` package holds the delta records and planners. It calls the existing verifier, sign-off, publisher and promotion code through their current entry points and does not reimplement them. A small set of seams are extended with delta-aware inputs: selection and parse (`validate.scan`), the verifier's target index, the claims source closure, and the publisher's per-member receipts. The CLI is the engine (Principle VI). The FastAPI routes shell out to it through `subprocess_runner`, and a Vue page exposes the same operations (Principle XI).

## Technical Context

**Language/Version**: Python 3.11+ (existing repo runtime); TypeScript + Vue 3 for the UI page

**Primary Dependencies**: Existing only. `campaignlib` for all model calls (`stream_api` / `call_api` / `make_client`); `pipelines/summary_native` modules; FastAPI + `server/subprocess_runner.py` for routes; Pinia/Vue Router for the page. No new third-party packages.

**Storage**: Files on disk, per Principle I. Run state, delta plans, baseline bindings, edit proposals, attestations and receipts are JSON/Markdown under the campaign's existing `docs/summaries/…/state/` and `docs/npcs/summary_native/` trees, plus the existing `docs/authority.yaml` ledger for approvals. No new database.

**Testing**: `pytest` (`python -m pytest tests/`), with new test modules per delta seam; Vitest (`npm test`) for the page; Playwright e2e only for the review flow if it is touched.

**Target Platform**: Linux workstation (the GM's machine); local browser for the UI; DGX Spark endpoint as the optional model backend.

**Project Type**: CLI engine + FastAPI server + Vue frontend (existing layout). This feature extends all three.

**Performance Goals**: Not latency-driven. The measurable targets are read-bound counts, not timings: for a one-new-chapter run, historical parse and extraction calls = 0 (SC-001); a no-op replay makes 0 content writes and 0 model calls (SC-006).

**Constraints**:
- No historical rescan, re-extraction or redrafting (FR-004, SC-001). Integrity hashing of exact custody dependencies is allowed and reported separately.
- No fabricated full-corpus receipt, verifier PASS, sign-off, or complete-coverage claim (FR-005, FR-021).
- Independent per-member NPC publication; no claim of group atomicity (FR-019).
- Secrets must never enter a drafting prompt (FR-012, SC-007).

**Scale/Scope**: About 75 chapters; roughly 100 NPC publications (10 updated and 3 new in the reference run, 96 unselected); four grounding documents plus timeline and reference tree. Each delta run selects one to a few chapters.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Checked against `.specify/memory/constitution.md` v2.0.0. Each principle is named, followed by how this plan satisfies it.

| # | Principle | Status | How the plan satisfies it / open risk |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | PASS | All delta state is files. Model output is written as a draft, and nothing reads it as canon until sign-off and promotion. The live editable grounding files are treated as disk truth and adopted explicitly (FR-003). |
| II | The Human Checkpoint is Non-Negotiable | PASS, with checkpoints listed | Precision decisions and their checkpoints: (a) the chapter selection, which is a human-chosen input; (b) the NPC census, where a human rules on each unresolved, indirect or excluded name; (c) contextual associations, where a human approves each one; (d) grounding edit proposals, where a human approves each replacement before reconstruction; (e) draft sign-off per item; (f) unchanged attestations; (g) publication authorization. Each LLM call is listed in research.md R3 with its input, decision and downstream reviewer. |
| III | Retrieval and Render are Separated | PASS | The delta planner and the census do not call `stream_api`. Retrieval (baseline/evidence selection) and rendering (draft, grounding edit proposals) remain in separate functions. `tests/test_retrieve_render_isolation.py` must still pass; the new modules are added to its scope. |
| IV | Verbatim is Sacred | PASS, with a required guard | Grounding edits are host-applied to stable line IDs, so untouched bytes never pass through a model. Quotes in new NPC history must still pass `check_quotes`. Claim kinds: baseline dossier body is `CLAIM_NONE` for quoting purposes. Traceability is universal: every new event and every edit names exact support, and inherited citations resolve through retained custody, not invented ones. |
| V | One Seam per Boundary | PASS | Anthropic calls go only through `campaignlib` (no `import anthropic` in `delta/`). Authority writes go only through `authority` modules. Routes shell out to the CLI; they do not import pipeline code directly. MemPalace is not used by this feature. |
| VI | CLI is the Engine, UI is a Face | PASS | Every operation is a CLI subcommand first. The router builds argv (`_build_delta_cmd()`) and streams output over SSE. Logic is never reimplemented in the router. |
| VII | Extract Once, Synthesize Deliberately | PASS | Existing #512 extraction caches are reused by content address. The delta does not merge extraction passes. It reuses the per-scene and per-NPC evidence it already has. |
| VIII | State is Discoverable | PASS | `delta/run.py` writes a versioned run state file that records each stage, its artifacts and its status. A UI status page and `summary_native delta status` both read that file. Stale, partial and recovery-required states are written, not inferred. |
| IX | The UI Mechanizes; Claude Converses | PASS | The page steps through stages and shows the files each stage produced. The census rulings, edit judgments and attestation reasons are entered through the CLI or the review page, and the page never holds state that exists only in the browser. |
| X | Selection is Explicit; There is No Silent "All" | PASS (central to design) | Sources are an explicit list of files (`--source`, repeatable). An empty list refuses. There is no glob or "latest" default. The UI "select all" writes every chapter it resolves into the explicit list. Baseline selection never uses "newest directory" (FR-002). |
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | PASS, UI required | The spec requires CLI and application parity (FR-022, SC-008). Not CLI-only. Every subcommand in `contracts/cli.md` has a route in `contracts/http.md` and a control on the delta page. No CLI-only ruling is recorded, and none is proposed. |
| XII | One Spelling per Option; No Configuration Drift | PASS, with a required audit | New options reuse the existing vocabulary: `--campaign-dir`, `--config`, `--json`, `--force`, `--backend`, `--model`, `--since`/`--until` where they still apply. New names are introduced across the whole `summary_native` family in the same change, not one script at a time (see research.md R9). Defaults are declared in the owning config model, not as literals in the router. |
| XIII | Breaking State Changes Migrate Out of Band | PASS, conditional | Research R8 found that promotion models inherit `StrictPromotionModel` (`extra="forbid"`), so adding fields to them breaks existing readers. The plan therefore keeps delta lineage in a new record and model, and adds no fields to strict models. If one does, the change is breaking. Then a one-shot migration CLI and `specs/039-incremental-campaign-updates/migration.md` are required before implementation, and this gate must be re-evaluated. Baseline adoption (FR-003) is an explicit operator act, not a silent upgrade. |

**Architecture is Destiny**: Token spend is bounded by the delta design. Only the selected chapters' sources are read and drafted, and historical drafts and evidence are reused by digest. The precision risks named by the constitution are the reason the human checkpoints above exist. No new daemon or cache is added. The only new recurring cost is the bounded consistency pass over the four documents, which is justified by FR-015.

**Authority & the Human Checkpoint**: This plan is a draft. It is reviewed against this constitution before tasks are generated. Any step where the planner would decide scope, ordering or attribution without a checkpoint is a violation and must be sent back.

**Result**: PASS for Phase 0. Conditional items: XIII (re-check after R8) and the Complexity Tracking rows below.

## Project Structure

### Documentation (this feature)

```text
specs/039-incremental-campaign-updates/
├── spec.md                  # Specification (rewritten from draft-input.md)
├── draft-input.md           # Original rough draft, kept as input
├── plan.md                  # This file
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output (validation guide, not code)
├── contracts/
│   ├── cli.md               # `summary_native delta …` command contract
│   └── http.md              # Server routes that mirror the CLI, plus SSE shape
├── checklists/requirements.md
└── tasks.md                 # NOT created here; produced by /speckit-tasks
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── delta/                         # NEW package: the feature's engine
│   ├── __init__.py
│   ├── plan.py                    # delta plan record; explicit source selection; refusals on empty set
│   ├── sources.py                 # selected-file ingestion; parse/read counters (SC-001)
│   ├── evidence.py                # typed FULL vs SPARSE evidence; explicit span targets (N2, FR-005)
│   ├── baseline.py                # grounding baseline binding + legacy/live adoption (FR-002/003, G4)
│   ├── npc_baseline.py            # per-NPC publication baseline selection from publish log (N1)
│   ├── census.py                  # NPC disposition census: changed/new/mention/absent/deferred/excluded/unresolved
│   ├── associations.py            # scoped contextual associations (N4); never adds a global alias
│   ├── attest.py                  # unchanged attestations bound to publication + evidence + rulings (N5, #585)
│   ├── grounding_edits.py         # host-owned line IDs, before-binding, categories, reconstruction (G1, FR-006/007)
│   ├── grounding_check.py         # bounded consistency + heading/table/citation preservation (FR-015)
│   ├── run.py                     # versioned durable run state, stages, member outcomes (C1, FR-018)
│   └── receipt.py                 # completion receipt (FR-024)
├── freshness.py                   # EXTENDED: per-item dependency closure (N3, FR-014)
├── npc_publish.py                 # EXTENDED: per-member outcome receipts; reconciliation (FR-019)
├── validate.py                    # EXTENDED: scan accepts an explicit `sources` list (G2)
├── corpus.py                      # EXTENDED: build_corpus accepts the same list
├── npc_verify.py                  # EXTENDED: build_index from SparseEvidence instead of chapter membership (N2)
├── promotion/manifest.py          # EXTENDED: reads a delta lineage record by pointer; no change to strict models (R8)
├── promotion/gates.py             # EXTENDED: new delta record kind with its own completeness rule; synth rule unchanged (G3)
├── claims/selection.py            # EXTENDED: inherited citations resolve through baseline custody (G3)
└── cli.py                         # EXTENDED: `delta` subcommand family (contracts/cli.md)

server/routers/
├── summary_native_delta.py        # NEW: thin routes that build argv and shell out via subprocess_runner
└── summary_native.py              # unchanged except router registration

frontend/src/
├── views/grounding/
│   └── DeltaRun.vue               # NEW: stage stepper, source picker (explicit), census, decisions, receipt
├── router.ts                      # EXTENDED: route to DeltaRun
└── (api client module)            # EXTENDED: delta endpoints

tests/
├── test_delta_sources.py          # SC-001 read counters; explicit-set refusal (X)
├── test_delta_evidence.py         # sparse-vs-full targets; no chapter-membership entries (N2)
├── test_delta_baseline.py         # baseline binding; adoption drift; no newest-directory choice (FR-002/003)
├── test_delta_grounding_edits.py  # stable IDs, overlap/duplicate rejection, byte preservation (SC-002)
├── test_delta_census.py           # full disposition census; unresolved never silent (N1)
├── test_delta_associations.py     # no global alias; rejected/Discuss not in drafting evidence (N4)
├── test_delta_attest.py           # attestation binding; original bytes preserved (N5)
├── test_delta_freshness.py        # B change does not stale A; shared change stales both (SC-005)
├── test_delta_run_resume.py       # failure injection at each durable boundary (SC-006)
├── test_delta_secrets.py          # canaries never in prompts/artifacts; audience refusal (SC-007)
├── test_delta_parity.py           # CLI vs router argv equivalence; same receipts (SC-008)
├── test_delta_grounding_e2e.py    # synthetic 2–3-chapter fixture; complete native delta (SC-009)
├── test_no_anthropic_in_delta.py  # Principle V guard
└── fixtures/delta/                # SYNTHETIC campaign fixture (no private campaign data)
```

**Structure Decision**: Option 2 (web application) of the default template, mapped onto the existing layout. Engine code is in `pipelines/summary_native/delta/`, the server is `server/`, and the page is in `frontend/src/views/grounding/`. There is no new top-level project.

## Phases and Gates

Delivery follows the spec's order. Each phase has a gate that must pass before the next starts. Every gate is an observable result, not a feeling.

- **Phase A: Foundation (P1).** Gate: SC-001 passes on the synthetic one-chapter fixture (historical parse count 0). Selected-source ingestion (G2). Full versus sparse evidence types (N2). Baseline binding and adoption records (G4, FR-002/003). Dependency bindings (N3). Run state (C1). Existing verifier and validate tests stay green, with golden outputs for full mode unchanged.
- **Phase B: NPC path (P1).** Gate: SC-004 changed/new/mention/mixed-horizon cases complete through public operations; SC-005 freshness cases; SC-007 Secrets canaries. Census (N1), associations (N4), attestations (N5, #585), typed sparse verification (N2), member receipts (FR-019).
- **Phase C: Grounding path (P1).** Gate: SC-002 byte preservation; SC-009 complete native delta with inherited citations and nested references. Host-owned edits (G1), bounded consistency (FR-015), claims/promotion delta lineage (G3, FR-016), whole-generation activation (reused).
- **Phase D: Workflow and UI (P2).** Gate: SC-008 CLI and router produce equivalent plans, decisions and receipts; restart preserves saved decisions (FR-023). Worktree transfer (FR-022). Route and page parity (XI). Operator-text correction (spec, Implementation section).

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New "delta" record kind accepted by the promotion gate (G3). This extends a gate; it does not bypass it. | Inherited Chapters 2–74 cannot be proven by a Chapter 75-only synth record, so the gate needs a delta-specific completeness rule. | Fabricating a one-chapter full-corpus manifest or a synth record is forbidden by FR-021 and fabricates coverage (SC-009). Weakening the gate for all records is worse. |
| Second evidence type, `SparseEvidence`, beside the full `CorpusIndex` (N2) | The current index treats every in-range chapter as having entry and moment targets (`npc_verify.py:273-276`). A sparse run must not inherit that. | Patching `CorpusIndex` in place would change the full-mode verifier output. Full-mode goldens must stay unchanged, so the types stay separate. |
| UI page added in the same feature (XI) | Required by the constitution and FR-022, not optional. | Deferring the UI to a follow-up is explicitly ruled out by XI. |

## Phase 0 and Phase 1 Outputs

- `research.md`: decisions R1–R11 with rationale and rejected alternatives. Resolves every open technical question in this plan.
- `data-model.md`: entities, fields and state transitions, mapped to the spec's Key Entities.

**Phase 1 re-check of the Constitution Check**: no new violations. XIII stays conditional on R8 (no strict-model fields). XI is satisfied by the parity map in `contracts/http.md`.
- `contracts/cli.md` and `contracts/http.md`: the operation surface, parity map and SSE shape.
- `quickstart.md`: runnable validation scenarios on the synthetic fixture.

## Execution Strategy (set by the user, 2026-11-06)

- **Coding**: Sonnet subagents, one per phase or per module group, each briefed with this plan, the relevant research decisions, and the contracts. They do not re-decide design.
- **Orchestration**: Opus, in the main thread. It sequences phases, enforces the phase gates above, checks each subagent's output against the tests, and does not write feature code itself.
- **Code review**: one review pass over the completed implementation, after Phase D. Findings that are real get fixed in that pass. Problems that remain after it are not left in the plan or in a comment: each becomes a GitHub issue with a link back to this spec.
- **Git**: work on branch `039-incremental-campaign-updates`, opened as a PR against `main`. Nothing merges without the user's go-ahead.

## Open Items (not blocking the plan; they block their own tasks)

1. **Fixture source.** The reference run used private campaign data (`~/campaigns/out-of-the-abyss`). Tests must not depend on it. Plan: a synthetic fixture under `tests/fixtures/delta/` that encodes the same shapes (forge restart, faction offer, passing mention, new NPC). The real Chapter 75 replay (SC-003) becomes a manual acceptance run, not a CI test. Confirm this choice before Phase A tasks are generated.
2. **Strict promotion models** (R8). Resolved for the design: delta lineage uses new models and a new record. If implementation finds that an existing strict model must gain a field, that is a breaking change, so XIII applies: stop, write `migration.md`, add a migration CLI, and re-run this gate.
